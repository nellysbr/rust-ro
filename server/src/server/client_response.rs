use std::io::Write;
use std::sync::mpsc::Receiver;

use crate::server::model::response::Response;
use crate::util::packet::{debug_packets_from_vec, PacketDirection};

/// A disconnected client must not stop responses to every other player.
pub(crate) fn run(receiver: Receiver<Response>, packetver: u32, trace_packet: bool) {
    while let Ok(response) = receiver.recv() {
        let socket = response.socket();
        let Ok(mut stream) = socket.write() else {
            warn!("Skipping response for a poisoned client socket");
            continue;
        };
        let peer = stream.peer_addr().ok();
        let data = response.serialized_packet();
        debug!("Respond to {:?} with: {:02X?}", peer, data);
        if trace_packet {
            debug_packets_from_vec(peer.as_ref(), PacketDirection::Backward, packetver, data, &None);
        }
        if let Err(error) = stream.write_all(data).and_then(|_| stream.flush()) {
            warn!("Failed to send response to {:?}: {}", peer, error);
        }
    }
    info!("Shutdown client_response_thread");
}
