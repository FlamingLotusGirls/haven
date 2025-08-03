use crate::model::RelayAddress;

pub struct ElderDefinition {
    pub artnet_target_ip_last_octet: u8,
    pub relay_narrow: RelayAddress,
    pub relay_wide: RelayAddress,
}

pub fn get_elder_defs() -> [ElderDefinition; 9] {
    [
        ElderDefinition {
            artnet_target_ip_last_octet: 51,
            relay_narrow: RelayAddress {
                board_address: 2,
                relay_number: 3,
            },
            relay_wide: RelayAddress {
                board_address: 2,
                relay_number: 4,
            },
        },
        ElderDefinition {
            artnet_target_ip_last_octet: 52,
            relay_narrow: RelayAddress {
                board_address: 2,
                relay_number: 5,
            },
            relay_wide: RelayAddress {
                board_address: 2,
                relay_number: 6,
            },
        },
        ElderDefinition {
            artnet_target_ip_last_octet: 53,
            relay_narrow: RelayAddress {
                board_address: 2,
                relay_number: 1,
            },
            relay_wide: RelayAddress {
                board_address: 2,
                relay_number: 2,
            },
        },
        ElderDefinition {
            artnet_target_ip_last_octet: 54,
            relay_narrow: RelayAddress {
                board_address: 1,
                relay_number: 1,
            },
            relay_wide: RelayAddress {
                board_address: 1,
                relay_number: 2,
            },
        },
        ElderDefinition {
            artnet_target_ip_last_octet: 55,
            relay_narrow: RelayAddress {
                board_address: 1,
                relay_number: 5,
            },
            relay_wide: RelayAddress {
                board_address: 1,
                relay_number: 6,
            },
        },
        ElderDefinition {
            artnet_target_ip_last_octet: 56,
            relay_narrow: RelayAddress {
                board_address: 1,
                relay_number: 3,
            },
            relay_wide: RelayAddress {
                board_address: 1,
                relay_number: 4,
            },
        },
        ElderDefinition {
            artnet_target_ip_last_octet: 57,
            relay_narrow: RelayAddress {
                board_address: 3,
                relay_number: 1,
            },
            relay_wide: RelayAddress {
                board_address: 3,
                relay_number: 2,
            },
        },
        ElderDefinition {
            artnet_target_ip_last_octet: 58,
            relay_narrow: RelayAddress {
                board_address: 3,
                relay_number: 5,
            },
            relay_wide: RelayAddress {
                board_address: 3,
                relay_number: 6,
            },
        },
        ElderDefinition {
            artnet_target_ip_last_octet: 59,
            relay_narrow: RelayAddress {
                board_address: 3,
                relay_number: 3,
            },
            relay_wide: RelayAddress {
                board_address: 3,
                relay_number: 4,
            },
        },
    ]
}
