#![no_std]
#![no_main]

mod artnet;
mod pixel_control;
mod ws2812_control;

use core::format_args as f;
use defmt_serial as _;
use embassy_executor::Spawner;
use embassy_net::{Config as NetConfig, Ipv4Address, Ipv4Cidr, Stack, StackResources};
use embassy_net_wiznet::Runner;
use embassy_rp::{
    bind_interrupts,
    gpio::{Input, Level, Output, Pull},
    peripherals::{BOOTSEL, PIO0, PIO1, SPI0, UART0},
    pio::{self, Pio},
    spi::{Async, Config as SpiConfig, Spi},
    uart,
};
use embassy_time::{Delay, Timer};
use embedded_hal_bus::spi::ExclusiveDevice;
use panic_probe as _;
use smart_leds::RGB8;
use static_cell::StaticCell;

use ws2812_control::{PioWs2812, PioWs2812Program};

// CONFIG
const PIXEL_COUNT: usize = 340;
const PIXEL_BYTE_SIZE: usize = PIXEL_COUNT * 3;
// 192.168.13.20-40 // Haven unSCruz 2026
// 169.254.3.10, 11, 20, 21, 30, 31, 40, 50, 60, 70 // Haven BM 2025
// 169.254.9.91-99 // Sea of Dreams unSCruz 2025
// 169.254.5.51 // Early testing

// Set controller for default colors, make sure to also set IP address.
const CONTROLLER: Option<&str> = Some("cockatoo_1");
const IP_ADDRESS_SECOND_TO_LAST_NUMBER: u8 = 13;
const IP_ADDRESS_LAST_NUMBER: u8 = 20;

/*
"cockatoo_1"   192.168.13.20
"cockatoo_2"   192.168.13.21
"cockatoo_3"   192.168.13.22
"magpie_1"     192.168.13.23
"magpie_2"     192.168.13.24
"osprey_1"     192.168.13.25
"osprey_2"     192.168.13.26
"egg_tub"      192.168.13.27
"zen_garden"   192.168.13.28
"bird_bath"    192.168.13.29
*/

// If you want to control CONTROLLER string via env variable at compile time:
// const CONTROLLER: Option<&str> = option_env!("CONTROLLER");

// Needed for tiny-artnet
#[global_allocator]
static HEAP: embedded_alloc::LlffHeap = embedded_alloc::LlffHeap::empty();

bind_interrupts!(struct Irqs {
    PIO0_IRQ_0 => pio::InterruptHandler<PIO0>;
    PIO1_IRQ_0 => pio::InterruptHandler<PIO1>;
});

#[embassy_executor::task]
async fn bootsel_task(mut bootsel: BOOTSEL) -> ! {
    loop {
        checkbootsel(&mut bootsel);
        Timer::after_secs(1).await;
    }
}
fn checkbootsel(bootsel: &mut BOOTSEL) {
    if bootsel.is_pressed() {
        embassy_rp::rom_data::reset_to_usb_boot(0, 0);
    }
}

struct UartWriter<'d, T: uart::Instance>(uart::Uart<'d, T, uart::Blocking>);
#[allow(dead_code)]
impl<T: uart::Instance> UartWriter<'_, T> {
    fn println(&mut self, args: core::fmt::Arguments) {
        let mut s: heapless::String<64> = heapless::String::new();
        let _ = core::fmt::write(&mut s, format_args!("{args}\n"));

        let _ = self.0.blocking_write(s.as_bytes());
        let _ = self.0.blocking_flush();
    }
    fn print(&mut self, args: core::fmt::Arguments) {
        let mut s: heapless::String<64> = heapless::String::new();
        let _ = core::fmt::write(&mut s, args);

        let _ = self.0.blocking_write(s.as_bytes());
        let _ = self.0.blocking_flush();
    }
}

#[embassy_executor::task]
#[allow(clippy::type_complexity)]
async fn ethernet_task(
    runner: Runner<
        'static,
        embassy_net_wiznet::chip::W5500,
        ExclusiveDevice<Spi<'static, SPI0, Async>, Output<'static>, Delay>,
        Input<'static>,
        Output<'static>,
    >,
) -> ! {
    runner.run().await
}

#[embassy_executor::task]

async fn net_task(
    mut runner: embassy_net::Runner<'static, embassy_net_wiznet::Device<'static>>,
) -> ! {
    runner.run().await
}

/// Fill pixel array with RGBW values in a repeating pattern (hack to fit RGBW into RGB, they are all going back to an array of bytes in the end)
fn fill_pixels_rgbw(pixels: &mut [RGB8], rgbw: [u8; 4]) {
    for (i, pixel) in pixels.iter_mut().enumerate() {
        let hack_index = i * 3;
        pixel.r = pixel_control::GAMMA[rgbw[hack_index % 4] as usize];
        pixel.g = pixel_control::GAMMA[rgbw[(hack_index + 1) % 4] as usize];
        pixel.b = pixel_control::GAMMA[rgbw[(hack_index + 2) % 4] as usize];
    }
}
fn fill_pixels_rgbw_no_gamma(pixels: &mut [RGB8], rgbw: [u8; 4]) {
    for (i, pixel) in pixels.iter_mut().enumerate() {
        let hack_index = i * 3;
        pixel.r = rgbw[hack_index % 4];
        pixel.g = rgbw[(hack_index + 1) % 4];
        pixel.b = rgbw[(hack_index + 2) % 4];
    }
}

/// Fill pixel array with solid color
fn fill_pixels(pixels: &mut [RGB8], rgb: [u8; 3]) {
    for pixel in pixels.iter_mut() {
        pixel.r = pixel_control::GAMMA[rgb[0] as usize];
        pixel.g = pixel_control::GAMMA[rgb[1] as usize];
        pixel.b = pixel_control::GAMMA[rgb[2] as usize];
    }
}

fn set_pixels_byte(pixels: &mut [RGB8], byte_offset: usize, value: u8) {
    match byte_offset % 3 {
        0 => {
            pixels[byte_offset / 3].r = pixel_control::GAMMA[value as usize];
        }
        1 => {
            pixels[byte_offset / 3].g = pixel_control::GAMMA[value as usize];
        }
        2 => {
            pixels[byte_offset / 3].b = pixel_control::GAMMA[value as usize];
        }
        _ => {
            pixels[byte_offset / 3].b = pixel_control::GAMMA[value as usize];
        }
    }
}

#[allow(dead_code)]
#[embassy_executor::main]
async fn main(spawner: Spawner) {
    let p = embassy_rp::init(Default::default());

    // Set up task for entering boot mode when holding bootsel button
    let _ = spawner.spawn(bootsel_task(p.BOOTSEL));

    // Set up serial printing
    static SERIAL: StaticCell<UartWriter<'_, UART0>> = StaticCell::new();
    let s = SERIAL.init_with(|| {
        UartWriter(uart::Uart::new_blocking(
            p.UART0,
            p.PIN_0,
            p.PIN_1,
            uart::Config::default(),
        ))
    });

    // Set up pixel control
    let mut pio_neopixel_0 = Pio::new(p.PIO1, Irqs);

    let program = PioWs2812Program::new(&mut pio_neopixel_0.common);
    let mut strip0: PioWs2812<'_, _, 0, PIXEL_COUNT, PIXEL_BYTE_SIZE> = PioWs2812::new(
        &mut pio_neopixel_0.common,
        pio_neopixel_0.sm0,
        p.DMA_CH4,
        p.PIN_6,
        &program,
    );
    let mut strip1: PioWs2812<'_, _, 1, PIXEL_COUNT, PIXEL_BYTE_SIZE> = PioWs2812::new(
        &mut pio_neopixel_0.common,
        pio_neopixel_0.sm1,
        p.DMA_CH5,
        p.PIN_7,
        &program,
    );
    let mut strip2: PioWs2812<'_, _, 2, PIXEL_COUNT, PIXEL_BYTE_SIZE> = PioWs2812::new(
        &mut pio_neopixel_0.common,
        pio_neopixel_0.sm2,
        p.DMA_CH6,
        p.PIN_8,
        &program,
    );
    let mut strip3: PioWs2812<'_, _, 3, PIXEL_COUNT, PIXEL_BYTE_SIZE> = PioWs2812::new(
        &mut pio_neopixel_0.common,
        pio_neopixel_0.sm3,
        p.DMA_CH7,
        p.PIN_9,
        &program,
    );

    let mut pixels = [RGB8::default(); PIXEL_COUNT];

    // Warning, these will all be gamma-corrected
    let _red = [255, 74, 38];
    let yellow = [255, 201, 38];
    let orange = [255, 100, 38];
    let green = [255, 208, 38];
    let cyan = [38, 255, 255];
    let blue = [38, 45, 255];
    let purple = [121, 38, 255];

    // rgb
    let cockatoo_window_1 = green;
    let cockatoo_window_2 = yellow;
    let cockatoo_window_3 = blue;
    let cockatoo_chandelier = cyan;
    let cockatoo_eyes = purple;
    let cockatoo_body = cyan;
    let cockatoo_button_panel = purple;

    let magpie_window_1 = yellow;
    let magpie_window_2 = blue;
    let magpie_eyes = blue;
    let magpie_button_panel = cyan;

    let osprey_window_1 = orange;
    let osprey_window_2 = blue;
    let osprey_button_panel = orange;

    let zen_garden_underlights = [19, 23, 127];
    let bird_bath_leds = purple;

    // rgbw
    let egg_tub_rgbw = [255, 10, 0, 100];
    let spotlights_rgbw = [255, 238, 153, 255];
    let cockatoo_cheeks_rgbw = [orange[0], orange[1], orange[2], 255];

    match CONTROLLER.unwrap_or("") {
        "cockatoo_1" => {
            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip0.write(&pixels).await;

            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip1.write(&pixels).await;

            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip2.write(&pixels).await;

            fill_pixels(&mut pixels, cockatoo_window_1);
            strip3.write(&pixels).await;
        }
        "cockatoo_2" => {
            fill_pixels(&mut pixels, cockatoo_window_2);
            strip0.write(&pixels).await;

            fill_pixels(&mut pixels, cockatoo_window_3);
            strip1.write(&pixels).await;

            fill_pixels(&mut pixels, cockatoo_chandelier);
            strip2.write(&pixels).await;

            fill_pixels(&mut pixels, purple);
            strip3.write(&pixels).await;
        }
        "cockatoo_3" => {
            // Cheeks (rgbw) are daisy chained to eyes (rgb) so we must do strange things
            let cheeks_rgbw_pixel_count = 8;
            let mut pixels_byte_index = 0;
            for _ in 0..cheeks_rgbw_pixel_count {
                for led in 0..4 {
                    set_pixels_byte(&mut pixels, pixels_byte_index, cockatoo_cheeks_rgbw[led]);
                    pixels_byte_index += 1;
                }
            }
            let eyes_pixel_count = 32;
            for _ in 0..eyes_pixel_count {
                for led in 0..3 {
                    set_pixels_byte(&mut pixels, pixels_byte_index, cockatoo_eyes[led]);
                    pixels_byte_index += 1;
                }
            }
            strip0.write(&pixels).await;

            fill_pixels(&mut pixels, cockatoo_body);
            strip1.write(&pixels).await;

            fill_pixels(&mut pixels, cockatoo_button_panel);
            strip2.write(&pixels).await;

            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip3.write(&pixels).await;
        }
        "magpie_1" => {
            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip0.write(&pixels).await;

            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip1.write(&pixels).await;

            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip2.write(&pixels).await;

            fill_pixels(&mut pixels, magpie_window_1);
            strip3.write(&pixels).await;
        }
        "magpie_2" => {
            fill_pixels(&mut pixels, magpie_window_2);
            strip0.write(&pixels).await;

            fill_pixels(&mut pixels, magpie_eyes);
            strip1.write(&pixels).await;

            fill_pixels(&mut pixels, magpie_button_panel);
            strip2.write(&pixels).await;

            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip3.write(&pixels).await;
        }
        "osprey_1" => {
            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip0.write(&pixels).await;

            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip1.write(&pixels).await;

            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip2.write(&pixels).await;

            fill_pixels(&mut pixels, osprey_window_1);
            strip3.write(&pixels).await;
        }
        "osprey_2" => {
            fill_pixels(&mut pixels, osprey_window_2);
            strip0.write(&pixels).await;

            fill_pixels(&mut pixels, osprey_button_panel);
            strip1.write(&pixels).await;

            fill_pixels(&mut pixels, yellow);
            strip2.write(&pixels).await;

            fill_pixels_rgbw(&mut pixels, spotlights_rgbw);
            strip3.write(&pixels).await;
        }
        "egg_tub" => {
            fill_pixels_rgbw_no_gamma(&mut pixels, egg_tub_rgbw);
            strip0.write(&pixels).await;
            strip1.write(&pixels).await;
            strip2.write(&pixels).await;
            strip3.write(&pixels).await;
        }
        "zen_garden" => {
            fill_pixels(&mut pixels, zen_garden_underlights);
            strip0.write(&pixels).await;
            strip1.write(&pixels).await;
            strip2.write(&pixels).await;
            strip3.write(&pixels).await;
        }
        "bird_bath" => {
            fill_pixels(&mut pixels, bird_bath_leds);
            strip0.write(&pixels).await;
            strip1.write(&pixels).await;
            strip2.write(&pixels).await;
            strip3.write(&pixels).await;
        }
        _ => {
            fill_pixels(&mut pixels, orange);
            strip0.write(&pixels).await;

            fill_pixels(&mut pixels, blue);
            strip1.write(&pixels).await;

            fill_pixels(&mut pixels, green);
            strip2.write(&pixels).await;

            fill_pixels(&mut pixels, purple);
            strip3.write(&pixels).await;
        }
    }

    strip2.write(&pixels).await;
    strip3.write(&pixels).await;

    // Connct to w5500 peripheral
    let mut spi_cfg = SpiConfig::default();
    spi_cfg.frequency = 50_000_000;
    let (miso, mosi, clk) = (p.PIN_16, p.PIN_19, p.PIN_18);
    let spi = Spi::new(p.SPI0, clk, mosi, miso, p.DMA_CH0, p.DMA_CH1, spi_cfg);
    let cs = Output::new(p.PIN_17, Level::High);
    let w5500_int = Input::new(p.PIN_21, Pull::Up);
    let w5500_reset = Output::new(p.PIN_20, Level::High);

    // Set up ethernet task
    let mac_addr = [
        0x00,
        0x00,
        0x00,
        0x00,
        IP_ADDRESS_SECOND_TO_LAST_NUMBER,
        IP_ADDRESS_LAST_NUMBER,
    ];
    static STATE: StaticCell<embassy_net_wiznet::State<8, 8>> = StaticCell::new();
    let state = STATE.init(embassy_net_wiznet::State::<8, 8>::new());
    let (w5500_device, ethernet_task_runner) = embassy_net_wiznet::new(
        mac_addr,
        state,
        ExclusiveDevice::new(spi, cs, Delay),
        w5500_int,
        w5500_reset,
    )
    .await
    .unwrap();
    spawner.spawn(ethernet_task(ethernet_task_runner)).unwrap();

    // for i in &mut pixels {
    //     i.r = 128;
    //     i.g = 0;
    //     i.b = 0;
    // }
    // strip0.write(&pixels).await;

    // Set up network stack
    let static_ip_net_config = NetConfig::ipv4_static(embassy_net::StaticConfigV4 {
        // Direct/unmanaged ethernet such as with switch GS308, or with direct connection to computer
        // address: Ipv4Cidr::new(
        //     Ipv4Address::new(
        //         169,
        //         254,
        //         IP_ADDRESS_SECOND_TO_LAST_NUMBER,
        //         IP_ADDRESS_LAST_NUMBER,
        //     ),
        //     16,
        // ),
        // Managed ethernet switch GS308T or router
        address: Ipv4Cidr::new(
            Ipv4Address::new(
                192,
                168,
                IP_ADDRESS_SECOND_TO_LAST_NUMBER,
                IP_ADDRESS_LAST_NUMBER,
            ),
            24,
        ),
        dns_servers: heapless::Vec::new(),
        gateway: None,
    });
    // let dhcp_net_config = NetConfig::dhcpv4(Default::default());
    static STACK_RESOURCES: StaticCell<StackResources<3>> = StaticCell::new();
    let seed = 0xafd4_37bc_79fd_c225;
    let (stack, net_task_runner) = embassy_net::new(
        w5500_device,
        static_ip_net_config,
        STACK_RESOURCES.init(StackResources::new()),
        seed,
    );
    spawner.spawn(net_task(net_task_runner)).unwrap();

    // for i in &mut pixels {
    //     i.r = 0;
    //     i.g = 128;
    //     i.b = 0;
    // }
    // strip0.write(&pixels).await;

    async fn wait_for_config(stack: Stack<'static>) -> embassy_net::StaticConfigV4 {
        use embassy_futures::yield_now;

        loop {
            if let Some(config) = stack.config_v4() {
                return config.clone();
            }
            yield_now().await;
        }
    }
    s.println(f!("waiting for stack config..."));
    wait_for_config(stack).await;
    s.println(f!("connected!"));

    // for i in &mut pixels {
    //     i.r = 0;
    //     i.g = 64;
    //     i.b = 255;
    // }
    // strip0.write(&pixels).await;

    artnet::receive_artnet(s, stack, strip0, strip1, strip2, strip3).await;

    // let delay = Duration::from_secs(1);
    // loop {
    //     checkbootsel(&mut p.BOOTSEL);
    //     s.println(f!("led on!"));
    //     cyw43_control.gpio_set(0, true).await;
    //     Timer::after(delay).await;

    //     checkbootsel(&mut p.BOOTSEL);
    //     s.println(f!("led off!"));
    //     cyw43_control.gpio_set(0, false).await;
    //     Timer::after(delay).await;
    // }
}
