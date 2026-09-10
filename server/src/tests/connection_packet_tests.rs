use packets::packets::{CharacterInfoNeoUnion, Packet, PacketHcAcceptMakecharNeoUnion, PacketZcAcceptEnter2, PacketZcAid};
use packets::packets_parser::{packet_len, parse};

use crate::server::request_handler::char::{created_character_packet, map_connection_packet};

#[test]
fn character_creation_serializes_database_fields_for_the_client_version() {
    for packetver in [20111102, 20120307] {
        // Mirrors the repository row mapper, which constructs version-neutral data.
        let mut character = CharacterInfoNeoUnion::new(0);
        let mut name = [0 as char; 24];
        for (i, c) in "RagzinProbe".chars().enumerate() {
            name[i] = c;
        }
        character.set_gid(150002);
        character.set_name(name);
        character.set_head(1);
        character.set_hair_color(0);
        character.set_hp(42);
        character.set_maxhp(42);
        character.set_char_num(1);
        character.fill_raw();

        let response = created_character_packet(character, packetver);
        assert_eq!(response.raw().len(), PacketHcAcceptMakecharNeoUnion::base_len(packetver));
        let decoded = parse(response.raw(), packetver);
        let decoded = decoded.as_any().downcast_ref::<PacketHcAcceptMakecharNeoUnion>().unwrap();
        assert_eq!(decoded.charinfo.gid, 150002);
        assert_eq!(decoded.charinfo.name, name);
        assert_eq!(decoded.charinfo.head, 1);
        assert_eq!(decoded.charinfo.hair_color, 0);
        assert_eq!(decoded.charinfo.hp, 42);
        assert_eq!(decoded.charinfo.char_num, 1);
    }
}

#[test]
fn map_greeting_preserves_the_following_map_entry_packet_boundary() {
    for packetver in [20111102, 20120307] {
        let greeting = map_connection_packet(2000000, packetver);
        assert_eq!(&greeting.raw()[..2], &[0x83, 0x02]);
        assert_eq!(greeting.raw().len(), 6);
        let mut entry = PacketZcAcceptEnter2::new(packetver);
        entry.set_start_time(987654);
        entry.set_pos_dir([13, 150, 240]);
        entry.fill_raw_with_packetver(Some(packetver));
        let mut stream = greeting.raw().clone();
        stream.extend(entry.raw());

        let greeting_len = packet_len([stream[0], stream[1]], packetver).unwrap();
        let decoded = parse(&stream[..greeting_len], packetver);
        let decoded = decoded.as_any().downcast_ref::<PacketZcAid>().unwrap();
        assert_eq!(decoded.aid, 2000000);
        let decoded = parse(&stream[greeting_len..], packetver);
        let decoded = decoded.as_any().downcast_ref::<PacketZcAcceptEnter2>().unwrap();
        assert_eq!(decoded.start_time, 987654);
        assert_eq!(decoded.pos_dir, [13, 150, 240]);
    }
}

#[test]
fn disconnected_client_does_not_stop_responses_to_other_players() {
    use std::io::Read;
    use std::net::{Shutdown, TcpListener, TcpStream};
    use std::sync::{mpsc, Arc, RwLock};
    use std::time::Duration;
    use crate::server::model::response::Response;

    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let _closed_client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (closed_socket, _) = listener.accept().unwrap();
    closed_socket.shutdown(Shutdown::Both).unwrap();
    let mut healthy_client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    healthy_client.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
    let (healthy_socket, _) = listener.accept().unwrap();
    let (sender, receiver) = mpsc::channel();
    let worker = std::thread::spawn(move || crate::server::client_response::run(receiver, 20120307, true));
    let packet = map_connection_packet(2000000, 20120307);
    for socket in [closed_socket, healthy_socket] {
        sender.send(Response::new(Arc::new(RwLock::new(socket)), packet.raw().clone())).unwrap();
    }
    drop(sender);
    let mut received = [0; 6];
    healthy_client.read_exact(&mut received).unwrap();
    assert_eq!(received.as_slice(), packet.raw());
    worker.join().expect("response worker survived the failed connection");
}
