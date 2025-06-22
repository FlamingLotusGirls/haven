use crate::model::{Elder, RelayAddress};
use serialport::{DataBits, SerialPortType, StopBits};
use std::{
    io::Write as _,
    sync::mpsc::{Sender, channel},
};

pub struct PooferBusPort {
    port_channel_sender: Sender<String>,
}
impl PooferBusPort {
    pub fn available_ports() -> Vec<String> {
        match serialport::available_ports() {
            Err(e) => {
                eprintln!("Error listing serial ports:");
                eprintln!("{e:?}");
                ::std::process::exit(1);
            }
            Ok(mut available_ports) => {
                available_ports.sort_by_key(|key| key.port_name.clone());

                available_ports
                    .iter()
                    .filter_map(|port| {
                        println!("{}", port.port_name);

                        match &port.port_type {
                            SerialPortType::UsbPort(info) => {
                                println!("  Type: USB");
                                println!("  VID: {:04x}", info.vid);
                                println!("  PID: {:04x}", info.pid);
                                println!(
                                    "  Serial Number: {}",
                                    info.serial_number.as_ref().map_or("", String::as_str)
                                );
                                println!(
                                    "  Manufacturer: {}",
                                    info.manufacturer.as_ref().map_or("", String::as_str)
                                );
                                println!(
                                    "  Product: {}",
                                    info.product.as_ref().map_or("", String::as_str)
                                );
                            }
                            SerialPortType::BluetoothPort => {
                                println!("  Type: Bluetooth");
                            }
                            SerialPortType::PciPort => {
                                println!("  Type: PCI");
                            }
                            SerialPortType::Unknown => {
                                println!("  Type: Unknown");
                            }
                        }
                        if matches!(port.port_type, SerialPortType::UsbPort(_)) {
                            Some(port.port_name.clone())
                        } else {
                            None
                        }
                    })
                    .collect::<Vec<String>>()
            }
        }
    }
    pub fn new(serial_port_name: &str) -> Self {
        let serial_port_name = serial_port_name.to_string();
        let (port_channel_sender, port_channel_receiver) = channel();
        std::thread::spawn(move || {
            let mut port = serialport::new(serial_port_name.clone(), 19200)
                .stop_bits(StopBits::One)
                .data_bits(DataBits::Eight)
                .open()
                .unwrap_or_else(|e| {
                    eprintln!("Failed to open port {}. Error: {}", serial_port_name, e);
                    ::std::process::exit(1);
                });
            loop {
                let command: String = port_channel_receiver.recv().unwrap();
                match port.write(command.as_bytes()) {
                    Ok(_) => {
                        println!("{}", command);
                        std::io::stdout().flush().unwrap();
                    }
                    Err(e) => eprintln!("{e:?}"),
                }
            }
        });

        Self {
            port_channel_sender,
        }
    }

    pub fn output(&self, elders: &mut Vec<Elder>) {
        for elder in elders {
            if elder.poofer_wide.needs_to_send_command {
                let RelayAddress {
                    board_address,
                    relay_number,
                } = &elder.poofer_wide.relay_address;
                let on_digit = elder.poofer_wide.on as u8;

                let command = format!("!{board_address:02}{relay_number}{on_digit}.");

                self.port_channel_sender.send(command).unwrap();
                elder.poofer_wide.needs_to_send_command = false;
            }
            if elder.poofer_narrow.needs_to_send_command {
                let RelayAddress {
                    board_address,
                    relay_number,
                } = &elder.poofer_narrow.relay_address;
                let on_digit = elder.poofer_narrow.on as u8;

                let command = format!("!{board_address:02}{relay_number}{on_digit}.");

                self.port_channel_sender.send(command).unwrap();
                elder.poofer_narrow.needs_to_send_command = false;
            }
        }
    }
}
