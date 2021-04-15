import sys


def bt(v):
    return int.from_bytes(v, "big")


def btr(v, s):
    r = int.from_bytes(v, "big")
    print(f"{s}: {r}")
    return r


# convert byte stream to MIDI variable length value
def vtime_bytes(a):
    bstrings = []
    for i in a[::-1]:
        bstrings.append(f"{i&127:07b}")
    return int("".join(bstrings[::-1]), 2)


# Simple tests
assert vtime_bytes([0x00]) == 0x00
assert vtime_bytes([0x40]) == 0x40
assert vtime_bytes([0x7F]) == 0x7F
assert vtime_bytes([0x81, 0x00]) == 0x80
assert vtime_bytes([0xC0, 0x00]) == 0x2000
assert vtime_bytes([0xFF, 0x7F]) == 0x3FFF
assert vtime_bytes([0x81, 0x80, 0x00]) == 0x4000
assert vtime_bytes([0xC0, 0x80, 0x00]) == 0x100000
assert vtime_bytes([0xFF, 0xFF, 0x7F]) == 0x1FFFFF
assert vtime_bytes([0x81, 0x80, 0x80, 0x00]) == 0x200000
assert vtime_bytes([0xC0, 0x80, 0x80, 0x00]) == 0x8000000
assert vtime_bytes([0xFF, 0xFF, 0xFF, 0x7F]) == 0xFFFFFFF


def read_vtime(ch, pos):
    sbt = []
    i = 0
    while i < 4:
        p = int(ch[pos + i])
        sbt.append(p)
        # Top bit cleared = end of number
        if p & 0x80 == 0:
            break
        i += 1
    return vtime_bytes(sbt), i + 1


def join_bytes_as_value(v):
    # TODO: use bt and btr (look up)
    return int("".join(f"{i:x}" for i in v), 16)


def interpret_midi_event(ch, pos, previous=None):

    msg_translate = {
        0b1000: (2, "note_off"),
        0b1001: (2, "note_on"),
        0b1010: (2, "key_pressure"),
        0b1011: (2, "control_change"),
        0b1100: (1, "program_change"),
        0b1101: (1, "channel_pressure"),
        0b1110: (2, "pitch_wheel"),
    }

    if previous is None:
        cpos = ch[pos]
    else:
        cpos = previous

    channel = cpos & 0x0F
    message = (cpos & 0xF0) >> 4
    assert message in msg_translate
    tmes = msg_translate[message]

    # data = [i & 0b01111111 for i in ch[pos + 1 : pos + 1 + tmes[0]]]
    if tmes[1] in ["program_change", "channel_pressure"]:
        data = (ch[pos + 1] & 0b01111111,)
    else:
        data = (ch[pos + 1] & 0b01111111, ch[pos + 2] & 0b01111111)
    return channel, message, tmes, data


def chunker(ch, track_size):
    pos = 0
    time_stamp = 0
    last_message = None
    while pos < track_size:
        val, offs = read_vtime(ch, pos)
        pos += offs
        time_stamp += val

        # --- RUNNING STATUS
        if ch[pos] < 0x80:
            assert last_message is not None
            # print(f"Running: {last_message:x} {ch[pos+1]:x} {ch[pos+2]:x}")
            # _, _, tmes = interpret_midi_event(ch, pos, previous=last_message, disp=True)
            channel, _, tmes, tdata = interpret_midi_event(ch, pos, previous=last_message)
            yield {"time": time_stamp, "type": tmes[1], "channel": channel, "data": tuple(tdata)}
            assert tmes[0] == 2
            pos += 2
            continue

        # --- META EVENT
        if ch[pos] == 0xFF:
            meta_num = ch[pos + 1]
            if meta_num == 0x2F:
                yield {"time": time_stamp, "type": "end_of_track", "data": pos + 3}
                assert pos + 3 == track_size
                pos += 3
                continue
            pos += 2
            val, offs = read_vtime(ch, pos)
            pos += offs

            meta_bytes = ch[pos : pos + val]
            if meta_num == 0x51:
                yield {
                    "time": time_stamp,
                    "type": "set_tempo",
                    "data": (join_bytes_as_value(meta_bytes),),
                }
            elif meta_num == 0x01:
                yield {"time": time_stamp, "type": "text", "data": meta_bytes}
            elif meta_num == 0x02:
                yield {"time": time_stamp, "type": "text_copyright", "data": meta_bytes}
            elif meta_num == 0x03:
                yield {"time": time_stamp, "type": "text_name", "data": meta_bytes}
            elif meta_num == 0x21:
                yield {"time": time_stamp, "type": "midi_port", "data": int(meta_bytes[0])}
            elif meta_num == 0x54:
                hr, mn, se, fr, ff = [int(i) for i in meta_bytes]
                yield {
                    "time": time_stamp,
                    "type": "smpte_offset",
                    "data": (hr, mn, se, fr, ff),
                }
            elif meta_num == 0x58:
                nn, dd, cc, bb = [int(i) for i in meta_bytes]
                yield {
                    "time": time_stamp,
                    "type": "time_signature",
                    "data": (nn, dd, cc, bb),
                }
            elif meta_num == 0x59:
                sf, mi = [int(i) for i in meta_bytes]
                yield {"time": time_stamp, "type": "key_signature", "data": (sf, mi)}
            else:
                print(f"Meta: 0x{meta_num:x} {ch[pos:pos+val]}")
                assert False
            # print(f"Meta: 0x{meta_num:x} -> {' '.join(hex(v) for v in ch[pos:pos+val])}")
            # val = meta data bytes
            pos += val
            last_message = None

        # --- SYSEX EVENT
        elif ch[pos] == 0xF0 or ch[pos] == 0xF7:
            # print(f"Sysex: {ch[pos+1]:x}")
            assert False, "Breaking on Sysex for debug reasons."
            while ch[pos] != 0xF7:
                pos += 1
            pos += 1

        # --- MIDI MESSAGE EVENT
        elif ch[pos] >= 0x80 and ch[pos] <= 0xEF:
            channel, _, tmes, tdata = interpret_midi_event(ch, pos)
            yield {"time": time_stamp, "type": tmes[1], "channel": channel, "data": tuple(tdata)}
            last_message = ch[pos]
            pos += tmes[0] + 1

        else:
            assert False, "Unknown code"


def read_tracks(chunks):
    tracks = []

    # read track chunks
    for ch_i, ch in enumerate(chunks):
        # track_size = btr(ch[0:4], "Track size")
        track_size = bt(ch[0:4])
        ch = ch[4:]
        assert track_size == len(ch)

        # parse all messages
        tracks.append(list(chunker(ch, track_size)))

    return tracks


def dump_midi(filename="Space Harrier.mid"):
    filename = "richter.mid"

    if len(sys.argv) == 2:
        # print("Loading from argument:", sys.argv[1])
        filename = sys.argv[1]

    with open(filename, "rb") as mf:
        content = mf.read()

        chunks = content.split(b"MTrk")
        # print("Chunks:", len(chunks))

        # MIDI file format description (just one picked from Google)
        # http://www.somascape.org/midi/tech/mfile.html
        # https://www.cs.cmu.edu/~music/cmsip/readings/MIDI%20tutorial%20for%20programmers.html
        # http://www.music.mcgill.ca/~ich/classes/mumt306/StandardMIDIfileformat.html#BMA1_

        # NOTE: MANY ASSUMPTIONS
        # header is location 0
        header_size = bt(chunks[0][4:8])
        chunks[0] = chunks[0][8:]
        # print("Header size:", header_size)
        h_format = bt(chunks[0][0:2])
        assert h_format == 1
        h_ntracks = bt(chunks[0][2:4])
        h_tickdiv = bt(chunks[0][4:6])
        assert len(chunks[0]) == header_size, f"Header size: {header_size} != {len(chunks[0])}"

        tracks = read_tracks(chunks[1:])
        # print(tracks[1])

        return (tracks, h_format, h_ntracks, h_tickdiv)


if __name__ == "__main__":
    tracks, m_format, m_ntracks, m_tickdiv = dump_midi()
    print(f"Format:{m_format}, nTracks:{m_ntracks}, Tickdiv:{m_tickdiv}")
    # print(tracks[1])
