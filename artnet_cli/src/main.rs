use clap::{Parser, Subcommand};
use std::net::UdpSocket;

// Art-Net standard port
const ARTNET_PORT: u16 = 6454;

#[derive(Parser)]
#[command(name = "artnet_cli")]
#[command(about = "Art-Net command-line utility for LED control", long_about = None)]
struct Cli {
    /// Target IP address (e.g., 192.168.1.100)
    #[arg(value_name = "IP")]
    target_ip: String,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Send save command to persist current LED state
    Save,

    /// Send DMX output with specified byte values
    Dmx {
        /// DMX data as hex string or decimal bytes
        /// Examples: "FF0000FF" or "255,0,0,255"
        #[arg(value_name = "DATA")]
        data: String,

        /// Universe number (default: 0)
        #[arg(short, long, default_value = "0")]
        universe: u8,
    },
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();

    let target_addr = format!("{}:{}", cli.target_ip, ARTNET_PORT);
    let socket = UdpSocket::bind("0.0.0.0:0")?;
    socket.set_nonblocking(false)?;

    match cli.command {
        Commands::Save => {
            send_save_command(&socket, &target_addr)?;
        }
        Commands::Dmx { data, universe } => {
            send_dmx_command(&socket, &target_addr, &data, universe)?;
        }
    }

    Ok(())
}

fn send_save_command(socket: &UdpSocket, target_addr: &str) -> Result<(), Box<dyn std::error::Error>> {
    println!("Sending save command to {}", target_addr);

    let command_data = b"save_defaults";
    let mut cmd_bytes = [0u8; 512];
    cmd_bytes[..command_data.len()].copy_from_slice(command_data);

    // Build Art-Net Command packet manually
    // Header: "Art-Net\0" (8 bytes)
    // OpCode: 0x8000 (2 bytes, little-endian) - ArtCommand
    // ProtVer: 14 (2 bytes, big-endian)
    // EstMan: 0x666c (2 bytes, little-endian) - OEM code "fl"
    // Cmd: filler (1 byte)
    // Filler: 9 bytes
    // Data: 512 bytes (command string)
    
    let mut packet = vec![
        b'A', b'r', b't', b'-', b'N', b'e', b't', 0x00,  // ID
        0x00, 0x80,                                        // OpCode: Command (0x8000, little-endian)
        0x00, 0x0e,                                        // ProtVer: 14 (big-endian)
    ];
    
    // OEM code: 0x666c (little-endian)
    packet.push(0x6c);
    packet.push(0x66);
    
    // E-ST Code
    packet.push(0x00);
    
    // Filler + Spare
    packet.extend_from_slice(&[0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]);
    
    // Command data (512 bytes)
    packet.extend_from_slice(&cmd_bytes);

    socket.send_to(&packet, target_addr)?;
    println!("✓ Save command sent successfully");

    Ok(())
}

fn send_dmx_command(
    socket: &UdpSocket,
    target_addr: &str,
    data: &str,
    universe: u8,
) -> Result<(), Box<dyn std::error::Error>> {
    println!("Sending DMX output to {} (universe {})", target_addr, universe);

    let dmx_data = parse_dmx_data(data)?;
    
    if dmx_data.is_empty() || dmx_data.len() > 512 {
        return Err(format!("DMX data must be 1-512 bytes, got {}", dmx_data.len()).into());
    }

    // Build Art-Net DMX packet manually
    // Header: "Art-Net\0" (8 bytes)
    // OpCode: 0x5000 (2 bytes, little-endian) - ArtDmx
    // ProtVer: 14 (2 bytes, big-endian)
    // Sequence: 0 (1 byte)
    // Physical: 0 (1 byte)
    // Universe: (2 bytes, little-endian)
    // Length: (2 bytes, big-endian)
    // Data: up to 512 bytes
    
    let mut packet = vec![
        b'A', b'r', b't', b'-', b'N', b'e', b't', 0x00,  // ID
        0x50, 0x00,                                        // OpCode: DMX (0x0050, little-endian)
        0x00, 0x0e,                                        // ProtVer: 14 (big-endian)
        0x00,                                              // Sequence
        0x00,                                              // Physical
    ];

    // Universe (little-endian)
    packet.push(universe);
    packet.push(0x00);

    // DMX data length (big-endian)
    let len = dmx_data.len() as u16;
    packet.push((len >> 8) as u8);
    packet.push((len & 0xff) as u8);

    // Add DMX data
    packet.extend_from_slice(&dmx_data);

    socket.send_to(&packet, target_addr)?;
    println!("✓ DMX output sent successfully ({} bytes)", dmx_data.len());

    Ok(())
}

fn parse_dmx_data(data: &str) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    // Try hex format first (e.g., "FF0000FF")
    if data.chars().all(|c| c.is_ascii_hexdigit()) {
        if data.len() % 2 != 0 {
            return Err("Hex data must have even number of characters".into());
        }
        let bytes: Result<Vec<u8>, _> = (0..data.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&data[i..i + 2], 16))
            .collect();
        return bytes.map_err(|e| e.to_string().into());
    }

    // Try comma-separated decimal format (e.g., "255,0,0,255")
    if data.contains(',') {
        let bytes: Result<Vec<u8>, _> = data
            .split(',')
            .map(|s| {
                s.trim()
                    .parse::<u8>()
                    .map_err(|e| format!("Invalid byte value: {}", e))
            })
            .collect();
        return bytes.map_err(|e| e.into());
    }

    // Try space-separated format
    if data.contains(' ') {
        let bytes: Result<Vec<u8>, _> = data
            .split_whitespace()
            .map(|s| {
                s.parse::<u8>()
                    .map_err(|e| format!("Invalid byte value: {}", e))
            })
            .collect();
        return bytes.map_err(|e| e.into());
    }

    Err("Data format not recognized. Use hex (FF0000), comma-separated (255,0,0), or space-separated (255 0 0)".into())
}
