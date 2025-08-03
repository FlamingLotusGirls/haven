use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4};

use crate::mapping::{get_elder_defs, ElderDefinition};

#[derive(Copy, Clone, Debug)]
pub struct Pixel {
    pub x: f32,
    pub y: f32,
    pub r: f32,
    pub g: f32,
    pub b: f32,
}

#[derive(Clone, Debug)]
pub struct Poofer {
    pub relay_address: RelayAddress,
    pub x: f32,
    pub y: f32,
    pub on: bool,
    pub needs_to_send_command: bool,
}
impl Poofer {
    pub fn poof(&mut self, new_value_of_on: bool) {
        match (self.on, new_value_of_on) {
            (true, false) => {
                self.on = false;
                self.needs_to_send_command = true;
            }
            (false, true) => {
                self.on = true;
                self.needs_to_send_command = true;
            }
            _ => {}
        }
    }
}

/**
 * Board address is based on dip switches. LSB is dip switch 1, MSB is dip switch 5. Putting the
 * switch in the direction of the arrow means 0; against the opposite direction of the arrow means
 * 1.
 *
 * Relay numbers within each board are one-indexed and there are up to 8.
 */
#[derive(Clone, Debug)]
pub struct RelayAddress {
    pub board_address: u8,
    pub relay_number: u8,
}

#[derive(Clone, Debug)]
pub struct Elder {
    pub artnet_target_addr: SocketAddr,
    pub crane_light: Pixel,
    pub poofer_wide: Poofer,
    pub poofer_narrow: Poofer,
}

/**
 * We use -1 to 1 for both X and Y axes.
 */
pub fn create_elders() -> Vec<Elder> {
    let starting_theta = std::f32::consts::FRAC_PI_2;
    let crane_light_radius: f32 = 0.4;
    let poofer_radius: f32 = 0.6;

    let elder_defs = get_elder_defs();
    let elder_count = elder_defs.len() as f32;
    elder_defs
        .into_iter()
        .enumerate()
        .map(
            |(
                i,
                ElderDefinition {
                    artnet_target_ip_last_octet,
                    relay_wide,
                    relay_narrow,
                },
            )| {
                let elder_theta = starting_theta + std::f32::consts::TAU * (i as f32) / elder_count;
                Elder {
                    artnet_target_addr: SocketAddrV4::new(
                        Ipv4Addr::new(169, 254, 5, artnet_target_ip_last_octet),
                        6454,
                    )
                    .into(),
                    crane_light: Pixel {
                        x: elder_theta.cos() * crane_light_radius,
                        y: elder_theta.sin() * crane_light_radius,
                        r: 0.,
                        g: 0.,
                        b: 0.,
                    },
                    poofer_wide: Poofer {
                        relay_address: relay_wide,
                        x: elder_theta.cos() * poofer_radius,
                        y: elder_theta.sin() * poofer_radius,
                        on: false,
                        needs_to_send_command: false,
                    },
                    poofer_narrow: Poofer {
                        relay_address: relay_narrow,
                        x: elder_theta.cos() * poofer_radius,
                        y: elder_theta.sin() * poofer_radius,
                        on: false,
                        needs_to_send_command: false,
                    },
                }
            },
        )
        .collect::<Vec<Elder>>()
}
