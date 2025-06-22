mod artnet_output_socket;
mod effects;
mod mapping;
mod model;
mod poofer_bus_port;
mod preview;

use iced::{
    ContentFit, Element, Event, Length, Padding, Settings, Size, Subscription, Task, Theme,
    application,
    keyboard::{self, Key},
    time,
    window::{self, events},
};
use model::create_elders;
use poofer_bus_port::PooferBusPort;
use std::time::{Duration, Instant};

use artnet_output_socket::ArtnetOutputSocket;
use effects::{Effect, get_ambient_effects, get_trigger_effects};

const ARTNET_FRAME_OUTPUT_PERIOD: usize = 2;

fn main() -> iced::Result {
    application("Haven Server", App::update, App::view)
        .theme(|_| Theme::Dark)
        .settings(Settings {
            antialiasing: true,
            ..Default::default()
        })
        .window(window::Settings {
            position: window::Position::SpecificWith(|window_size, monitor_dimens| {
                (0., (monitor_dimens.height / 2.) - (window_size.height / 2.)).into()
            }),
            ..Default::default()
        })
        .subscription(App::subscription)
        .run_with(App::new)
}

struct App {
    main_window_size: Size,
    preview: preview::Preview,
    start: Instant,
    ambient_effect_start: Instant,
    trigger_effect_start: Instant,
    current_ambient_effect: usize,
    current_trigger_effect: Option<usize>,
    ambient_effects: Vec<Box<dyn Effect>>,
    trigger_effects: Vec<Box<dyn Effect>>,
    artnet_socket: ArtnetOutputSocket,
    artnet_output_enabled: bool,
    artnet_output_frame_count: usize,
    poofer_output_enabled: bool,
    poofer_output_enabled_once: bool,
    available_serial_ports: Vec<String>,
    poofer_port: Option<PooferBusPort>,
}

#[allow(clippy::enum_variant_names)]
#[allow(dead_code)]
#[derive(Debug, Clone)]
enum Message {
    SetWindowSize(Size),
    Tick(Instant),
    ArtnetOutputCheckboxPressed,
    PooferOutputCheckboxPressed,
    SelectAmbientEffect(usize),
    SelectTriggerEffect(usize),
    SelectSerialPort(String),
    ElderDown(usize),
    ElderUp(usize),
}
impl App {
    fn new() -> (Self, Task<Message>) {
        (
            App {
                main_window_size: Size::new(0., 0.),
                preview: preview::Preview::new(create_elders()),
                start: Instant::now(),
                ambient_effect_start: Instant::now(),
                trigger_effect_start: Instant::now(),
                current_ambient_effect: 0,
                current_trigger_effect: None,
                ambient_effects: get_ambient_effects(),
                trigger_effects: get_trigger_effects(),
                artnet_socket: ArtnetOutputSocket::new(),
                artnet_output_enabled: true,
                artnet_output_frame_count: 0,
                poofer_output_enabled: false,
                poofer_output_enabled_once: false,
                available_serial_ports: PooferBusPort::available_ports(),
                poofer_port: None,
            },
            window::get_latest()
                .and_then(window::get_size)
                .map(Message::SetWindowSize),
        )
    }
    fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::SetWindowSize(size) => {
                self.main_window_size = size;
                Task::none()
            }
            Message::Tick(now) => {
                // Clear all pixels
                for pixel in self.preview.0.iter_mut() {
                    pixel.crane_light.r = 0.;
                    pixel.crane_light.g = 0.;
                    pixel.crane_light.b = 0.;
                }

                self.ambient_effects[self.current_ambient_effect].render(
                    &mut self.preview.0,
                    now - self.start,
                    now - self.ambient_effect_start,
                );
                if let Some(current_trigger_effect) = self.current_trigger_effect {
                    self.trigger_effects[current_trigger_effect].render(
                        &mut self.preview.0,
                        now - self.start,
                        now - self.trigger_effect_start,
                    );
                }

                if self.artnet_output_enabled {
                    if self.artnet_output_frame_count == 0 {
                        self.artnet_socket.output(&self.preview.0);
                    }
                    self.artnet_output_frame_count =
                        (self.artnet_output_frame_count + 1) % ARTNET_FRAME_OUTPUT_PERIOD;
                }

                if let Some(poofer_port) = &mut self.poofer_port {
                    if self.poofer_output_enabled || self.poofer_output_enabled_once {
                        poofer_port.output(&mut self.preview.0);
                        self.poofer_output_enabled_once = false;
                    }
                }

                self.preview.request_redraw();

                Task::none()
            }
            Message::ArtnetOutputCheckboxPressed => {
                self.artnet_output_enabled = !self.artnet_output_enabled;
                Task::none()
            }
            Message::PooferOutputCheckboxPressed => {
                if self.poofer_output_enabled {
                    self.turn_poofers_off();
                    self.poofer_output_enabled_once = true;
                    self.poofer_output_enabled = false;
                } else {
                    self.poofer_output_enabled = true;
                }
                Task::none()
            }
            Message::SelectAmbientEffect(i) => {
                self.turn_poofers_off();
                self.current_ambient_effect = i;
                self.ambient_effect_start = Instant::now();
                Task::none()
            }
            Message::SelectTriggerEffect(i) => {
                self.turn_poofers_off();
                if self.current_trigger_effect == Some(i) {
                    self.current_trigger_effect = None;
                } else {
                    self.current_trigger_effect = Some(i);
                }
                self.trigger_effect_start = Instant::now();
                Task::none()
            }
            Message::SelectSerialPort(port_name) => {
                self.poofer_port = Some(PooferBusPort::new(&port_name));
                Task::none()
            }
            Message::ElderDown(elder_i) => {
                self.preview.0[elder_i].poofer_narrow.poof(true);
                self.preview.0[elder_i].poofer_wide.poof(true);
                Task::none()
            }
            Message::ElderUp(elder_i) => {
                self.preview.0[elder_i].poofer_narrow.poof(false);
                self.preview.0[elder_i].poofer_wide.poof(false);
                Task::none()
            }
        }
    }

    fn view(&self) -> Element<Message> {
        use iced::widget::{column, *};
        container(column![
            row![
                container(column(self.ambient_effects.iter().enumerate().map(
                    |(i, effect)| {
                        (button(text(effect.name()))
                            .style(if i == self.current_ambient_effect {
                                button::primary
                            } else {
                                button::secondary
                            })
                            .on_press(Message::SelectAmbientEffect(i)))
                        .into()
                    }
                ))),
                container(column(self.trigger_effects.iter().enumerate().map(
                    |(i, effect)| {
                        (button(text(effect.name()))
                            .style(if Some(i) == self.current_trigger_effect {
                                button::primary
                            } else {
                                button::secondary
                            })
                            .on_press(Message::SelectTriggerEffect(i)))
                        .into()
                    }
                ))),
                container(responsive(move |bounds| {
                    let Size { width, height } = ContentFit::Contain.fit(Size::new(1., 1.), bounds);
                    center(
                        canvas(&self.preview)
                            .width(Length::Fixed(width))
                            .height(Length::Fixed(height)),
                    )
                    .into()
                }))
                .width(Length::Fill)
                .height(Length::Fill),
                column![
                    checkbox("Output LEDs", self.artnet_output_enabled)
                        .on_toggle(|_| { Message::ArtnetOutputCheckboxPressed }),
                    checkbox("Output Poofers", self.poofer_output_enabled)
                        .on_toggle(|_| { Message::PooferOutputCheckboxPressed }),
                    column(self.available_serial_ports.iter().map(|port_name| {
                        button(text(port_name))
                            .on_press(Message::SelectSerialPort(port_name.clone()))
                            .into()
                    })),
                ],
            ],
            container(
                row(self.preview.0.iter().enumerate().map(|(i, elder)| {
                    let number = i + 1;
                    mouse_area(
                        button(text(format!("      \n{number}\n      "))).padding(Padding {
                            left: 10.,
                            right: 10.,
                            top: 10.,
                            bottom: 10.,
                        }),
                    )
                    .on_press(Message::ElderDown(i))
                    .on_enter(Message::ElderDown(i))
                    .on_release(Message::ElderUp(i))
                    .on_exit(Message::ElderUp(i))
                    .into()
                }))
                .width(Length::Fill)
            )
        ])
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
    }

    fn subscription(&self) -> Subscription<Message> {
        Subscription::batch([
            time::every(Duration::from_millis(10)).map(Message::Tick),
            // events().map(|event| {
            //     match event {
            //         (
            //             _window_id,
            //             Event::Keyboard(keyboard::Event::KeyPressed {
            //                 key,
            //                 modified_key,
            //                 physical_key,
            //                 location,
            //                 modifiers,
            //                 text,
            //             }),
            //         ) => Message::ElderDown(match key {
            //             Key::Character("1") => {}
            //         }), // keyboard::Event::KeyReleased { key, location, modifiers } => {}
            //     }
            // }),
        ])
    }

    fn turn_poofers_off(&mut self) {
        for elder in &mut self.preview.0 {
            elder.poofer_wide.poof(false);
            elder.poofer_narrow.poof(false);
        }
    }
}
