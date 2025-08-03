use core::format_args as f;
use embassy_net::IpAddress;
use embassy_rp::{peripherals::UART0, pio};
use smart_leds::RGB8;

use crate::{ws2812_control::PioWs2812, UartWriter, PIXEL_BYTE_SIZE, PIXEL_COUNT};

pub async fn receive_artnet<P: pio::Instance>(
    s: &mut UartWriter<'_, UART0>,
    stack: embassy_net::Stack<'static>,
    mut strip0: PioWs2812<'_, P, 0, PIXEL_COUNT, PIXEL_BYTE_SIZE>,
    mut strip1: PioWs2812<'_, P, 1, PIXEL_COUNT, PIXEL_BYTE_SIZE>,
    mut strip2: PioWs2812<'_, P, 2, PIXEL_COUNT, PIXEL_BYTE_SIZE>,
    mut strip3: PioWs2812<'_, P, 3, PIXEL_COUNT, PIXEL_BYTE_SIZE>,
) {
    use embassy_net::udp::{PacketMetadata, UdpSocket};

    s.println(f!("Connected!"));
    let address_uints = stack.config_v4().unwrap().address.address().octets();
    s.println(f!(
        "IP Address: {}.{}.{}.{}",
        address_uints[0],
        address_uints[1],
        address_uints[2],
        address_uints[3]
    ));
    let hardware_address = stack.hardware_address();
    let hardware_address_uints = hardware_address.as_bytes();
    s.println(f!(
        "MAC Address: {:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}",
        hardware_address_uints[0],
        hardware_address_uints[1],
        hardware_address_uints[2],
        hardware_address_uints[3],
        hardware_address_uints[4],
        hardware_address_uints[5]
    ));

    let mut rx_meta = [PacketMetadata::EMPTY; 16];
    let mut rx_buffer = [0; 16384];
    let mut tx_meta = [PacketMetadata::EMPTY; 16];
    let mut tx_buffer = [0; 1024];
    // let mut buf = [0; 65507];
    let mut buf = [0; 1024];

    let mut socket = UdpSocket::new(
        stack,
        &mut rx_meta,
        &mut rx_buffer,
        &mut tx_meta,
        &mut tx_buffer,
    );
    socket.bind(tiny_artnet::PORT).unwrap();
    s.println(f!("Artnet port bound"));

    // pixels_0[0] = RGB8::new(255, 0, 255);
    // strip0.write(pixels_0).await;

    // DEBUG
    let mut last_sequence: u8 = 0;

    // let mut pixels_0 = [RGB8::default(); PIXEL_COUNT];
    // let mut pixels_1 = [RGB8::default(); PIXEL_COUNT];
    // let mut pixels_2 = [RGB8::default(); PIXEL_COUNT];
    // let mut pixels_3 = [RGB8::default(); PIXEL_COUNT];
    let mut pixels_0_uints = [0u32; PIXEL_COUNT];
    let mut pixels_1_uints = [0u32; PIXEL_COUNT];
    let mut pixels_2_uints = [0u32; PIXEL_COUNT];
    let mut pixels_3_uints = [0u32; PIXEL_COUNT];
    loop {
        let (packet_length, metadata) = socket.recv_from(&mut buf).await.unwrap();

        // s.print(f!("Received a packet of length {}", packet_length));

        // if packet_length >= 8 {
        //     s.println(f!(
        //         " with these first 8 bytes: {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x}",
        //         buf[0],
        //         buf[1],
        //         buf[2],
        //         buf[3],
        //         buf[4],
        //         buf[5],
        //         buf[6],
        //         buf[7]));
        // } else {
        //     s.println(f!(" which is less than 8 bytes long"));
        // }

        // let data_size: usize = 512;
        let pixels_per_universe: usize = 512 / 3;
        match tiny_artnet::from_slice(&buf[..packet_length]) {
            Ok(tiny_artnet::Art::Dmx(dmx)) => {
                // s.println(f!("received artnet: dmx"));

                // The dmx.port_address.as_index() calculation is wrong so I am doing my own.
                // let port_address = dmx.port_address.as_index();
                let port_address = ((dmx.port_address.net as usize) << 8)
                    + ((dmx.port_address.sub_net as usize) << 4)
                    + (dmx.port_address.universe as usize);
                // s.println(f!("port_address: {port_address:?}"));

                // DEBUG
                if port_address == 31 {
                    let sequence = dmx.sequence;
                    if sequence != last_sequence.wrapping_add(1) {
                        s.println(f!(
                            "seq: {} ; skipped: {}",
                            sequence,
                            sequence - last_sequence + 1
                        ));
                    }
                    last_sequence = sequence;
                }

                let start_of_universe_in_pixel_array = (port_address % 10) * pixels_per_universe;
                let byte_write_start = start_of_universe_in_pixel_array * 3;
                // let byte_write_end = byte_write_start + dmx.data.len();
                let data_iter = dmx
                    .data
                    .chunks_exact(3)
                    .take((PIXEL_COUNT - start_of_universe_in_pixel_array).max(0));
                // .enumerate();
                if port_address < 10 {
                    data_iter
                        .zip(
                            pixels_0_uints
                                .iter_mut()
                                .skip(start_of_universe_in_pixel_array),
                        )
                        .for_each(|(dmx_pixel, pixel_uint)| {
                            *pixel_uint = (u32::from(dmx_pixel[0]) << 24)
                                | (u32::from(dmx_pixel[1]) << 16)
                                | (u32::from(dmx_pixel[2]) << 8);
                        });
                    // data_iter.for_each(|(i, pixel)| {
                    //     // pixels_0[start_of_universe_in_pixel_array + i] =
                    //     //     RGB8::new(pixel[0], pixel[1], pixel[2]);
                    //     pixels_0_uints[start_of_universe_in_pixel_array + i] = *pixel;
                    // });
                    // pixels_0_uints[byte_write_start..byte_write_end].copy_from_slice(dmx.data);
                    if start_of_universe_in_pixel_array == 0 {
                        // strip0.write(&pixels_0).await;
                        strip0.write_uints(&pixels_0_uints).await;
                    }
                } else if port_address < 20 {
                    data_iter
                        .zip(
                            pixels_1_uints
                                .iter_mut()
                                .skip(start_of_universe_in_pixel_array),
                        )
                        .for_each(|(dmx_pixel, pixel_uint)| {
                            *pixel_uint = (u32::from(dmx_pixel[0]) << 24)
                                | (u32::from(dmx_pixel[1]) << 16)
                                | (u32::from(dmx_pixel[2]) << 8);
                        });
                    // data_iter.for_each(|(i, pixel)| {
                    //     // pixels_1[start_of_universe_in_pixel_array + i] =
                    //     //     RGB8::new(pixel[0], pixel[1], pixel[2]);
                    //     pixels_1_uints[start_of_universe_in_pixel_array + i] = *pixel;
                    // });
                    // pixels_1_uints[byte_write_start..byte_write_end].copy_from_slice(dmx.data);
                    if start_of_universe_in_pixel_array == 0 {
                        // strip1.write(&pixels_1).await;
                        strip1.write_uints(&pixels_1_uints).await;
                    }
                } else if port_address < 30 {
                    data_iter
                        .zip(
                            pixels_2_uints
                                .iter_mut()
                                .skip(start_of_universe_in_pixel_array),
                        )
                        .for_each(|(dmx_pixel, pixel_uint)| {
                            *pixel_uint = (u32::from(dmx_pixel[0]) << 24)
                                | (u32::from(dmx_pixel[1]) << 16)
                                | (u32::from(dmx_pixel[2]) << 8);
                        });
                    // data_iter.for_each(|(i, pixel)| {
                    //     // pixels_2[start_of_universe_in_pixel_array + i] =
                    //     //     RGB8::new(pixel[0], pixel[1], pixel[2]);
                    //     pixels_2_uints[start_of_universe_in_pixel_array + i] = *pixel;
                    // });
                    // pixels_2_uints[byte_write_start..byte_write_end].copy_from_slice(dmx.data);
                    if start_of_universe_in_pixel_array == 0 {
                        // strip2.write(&pixels_2).await;
                        strip2.write_uints(&pixels_2_uints).await;
                    }
                } else if port_address < 40 {
                    data_iter
                        .zip(
                            pixels_3_uints
                                .iter_mut()
                                .skip(start_of_universe_in_pixel_array),
                        )
                        .for_each(|(dmx_pixel, pixel_uint)| {
                            *pixel_uint = (u32::from(dmx_pixel[0]) << 24)
                                | (u32::from(dmx_pixel[1]) << 16)
                                | (u32::from(dmx_pixel[2]) << 8);
                        });
                    // data_iter.for_each(|(i, pixel)| {
                    //     // pixels_3[start_of_universe_in_pixel_array + i] =
                    //     //     RGB8::new(pixel[0], pixel[1], pixel[2]);
                    //     pixels_3_uints[start_of_universe_in_pixel_array + i] = *pixel;
                    // });
                    // pixels_3_uints[byte_write_start..byte_write_end].copy_from_slice(dmx.data);
                    if start_of_universe_in_pixel_array == 0 {
                        // strip3.write(&pixels_3).await;
                        strip3.write_uints(&pixels_3_uints).await;
                    }
                }
            }
            Ok(tiny_artnet::Art::Poll(_poll)) => {
                s.println(f!("received artnet: poll"));
                let reply = tiny_artnet::PollReply {
                    ip_address: &address_uints,
                    port: tiny_artnet::PORT,
                    mac_address: &{
                        let mut a = [0u8; 6];
                        a.iter_mut()
                            .zip(hardware_address_uints.iter())
                            .for_each(|(a, b)| *a = *b);
                        a
                    },
                    ..Default::default()
                };

                let poll_reply_len = reply.serialize(&mut buf);

                s.print(f!("sending reply of length {}", poll_reply_len));
                let IpAddress::Ipv4(x) = metadata.endpoint.addr;
                s.println(f!(
                    " to {}.{}.{}.{}:{}",
                    x.octets()[0],
                    x.octets()[1],
                    x.octets()[2],
                    x.octets()[3],
                    metadata.endpoint.port
                ));

                match socket
                    .send_to(&buf[..poll_reply_len], metadata.endpoint)
                    .await
                {
                    Ok(_) => {
                        s.println(f!("sent poll reply"));
                    }
                    Err(_) => {
                        s.println(f!("error sending poll reply"));
                    }
                }
            }
            Ok(tiny_artnet::Art::Command(_)) => {
                s.println(f!("received artnet: command"));
            }
            Ok(tiny_artnet::Art::Sync) => {
                s.println(f!("received artnet: sync"));
            }
            Err(_) => {
                s.println(f!("received artnet: error"));
            }
        }
    }
}
