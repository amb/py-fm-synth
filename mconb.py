import mido
from collections import defaultdict
import time
import sys
from asciimatics.screen import Screen


filename = "Space Harrier.mid"
# filename = "Shovel.mid"

if len(sys.argv) == 2:
    print("Loading from argument:", sys.argv[1])
    filename = sys.argv[1]


def load_with_mido(filename):
    from mido import MidiFile

    mid = MidiFile(filename, clip=True)
    # print("Loading:", mid)
    # print("Ticks per beat:", mid.ticks_per_beat)
    # print("Type:", mid.type)

    notes = defaultdict(list)
    song_length = 0
    for track_i, track in enumerate(mid.tracks):
        # print("Loading track:", track_i)
        # notes = defaultdict(list)
        timestamp = 0
        for msg in track:
            timestamp += msg.time

            if msg.type == "note_on" or msg.type == "note_off":
                # notes[timestamp].append((msg.type, msg.channel, msg.note, msg.velocity))
                notes[timestamp].append(
                    {"type": msg.type, "channel": msg.channel, "data": (msg.note, msg.velocity)}
                )
            elif msg.type == "program_change":
                # notes[timestamp].append((msg.type, msg.channel, msg.program))
                notes[timestamp].append(
                    {"type": msg.type, "channel": msg.channel, "data": (msg.program,)}
                )
            elif msg.type == "set_tempo":
                # notes[timestamp].append((msg.type, msg.tempo))
                notes[timestamp].append({"type": msg.type, "data": (msg.tempo,)})
            elif msg.type == "control_change":
                # notes[timestamp].append((msg.type, msg.channel, msg.control, msg.value))
                notes[timestamp].append(
                    {"type": msg.type, "channel": msg.channel, "data": (msg.control, msg.value)}
                )
            elif msg.type == "pitchwheel":
                # notes[timestamp].append((msg.type, msg.channel, msg.pitch))
                notes[timestamp].append(
                    {"type": "pitch_wheel", "channel": msg.channel, "data": (msg.pitch,)}
                )
            elif msg.type == "end_of_track":
                pass
            elif msg.type == "track_name":
                pass
            elif msg.type == "midi_port":
                pass
            # else:
            #     print(timestamp, msg)
            #     # assert False
        # track_notes.append(notes)
        if timestamp > song_length:
            song_length = timestamp

    return notes, song_length, mid.ticks_per_beat


def load_with_mididump(filename):
    import mididump

    tracks, m_format, m_ntracks, m_tickdiv = mididump.dump_midi(filename)
    # TODO: could use end_of_track here
    song_length = max(i[-1]["time"] for i in tracks)

    # data transform
    track_notes = defaultdict(list)
    for ti, t in enumerate(tracks):
        for m in t:
            if m["type"] == "pitch_wheel":
                # TODO: 7-bit lsb msb, needs validation
                p = m["data"][0] + ((m["data"][1] - 64) * 128)
                m["data"] = (p,)
            track_notes[m["time"]].append(m)

    return track_notes, song_length, m_tickdiv


track_notes, song_length, tickdiv = load_with_mido(filename)
# print("Song length:", song_length)


def play_song(player, sleng, tnotes, tickdiv, screen):
    # play the song
    text_offset = 16
    start = time.time()
    tempo = 500000
    for i in range(sleng):
        # convert MIDI tick to seconds
        frac_time = i * tempo * 1e-6 / tickdiv
        notes = []
        # for ti, t in enumerate(tnotes):
        t = tnotes[i]
        # go through each event
        for m in t:
            # print(m)
            msg = m["type"]
            # n: (type, note, velocity)
            if msg == "note_on":
                player.send(
                    mido.Message(
                        "note_on",
                        note=m["data"][0],
                        velocity=m["data"][1],
                        channel=m["channel"],
                    )
                )
            elif msg == "note_off":
                player.send(
                    mido.Message(
                        "note_off",
                        note=m["data"][0],
                        velocity=m["data"][1],
                        channel=m["channel"],
                    )
                )
            elif msg == "program_change":
                player.send(
                    mido.Message("program_change", program=m["data"][0], channel=m["channel"])
                )
                screen.print_at("   ", text_offset - 3, m["channel"], colour=1, bg=0)
                col = m["channel"] % 7 + 1
                screen.print_at(m["data"][0], text_offset - 3, m["channel"], colour=col, bg=0)
            elif msg == "set_tempo":
                tempo = m["data"][0]
            elif msg == "control_change":
                player.send(
                    mido.Message(
                        "control_change",
                        control=m["data"][0],
                        value=m["data"][1],
                        channel=m["channel"],
                    )
                )
            elif msg == "pitch_wheel":
                player.send(mido.Message("pitchwheel", pitch=m["data"][0], channel=m["channel"]))
            elif msg in [
                "text_name",
                "text_copyright",
                "text",
                "end_of_track",
                "midi_port",
                "smpte_offset",
                "time_signature",
                "key_signature",
            ]:
                pass
            else:
                print(msg)
                assert False
            # if n[0] in ["note_on", "note_off"]:
            if msg == "note_on":
                notes.append(
                    f"{m['channel']}:{'+' if msg=='note_on' else '-'}"
                    f"{m['data'][0]:02x}.{m['data'][1]:02x} "
                )

                col = m["channel"] % 7 + 1 if m["data"][1] > 0 else 0
                screen.print_at("*", m["data"][0] + text_offset, m["channel"], colour=col, bg=0)

            if msg == "note_off":
                screen.print_at(" ", m["data"][0] + text_offset, m["channel"], colour=0, bg=0)

        # ev = screen.get_key()
        # if ev in (ord("Q"), ord("q")):
        #     return
        screen.refresh()

        # if notes:
        #     print("".join(notes))

        # wait until real time meets frac_time
        # on windows there's not enough resolution when using time.sleep
        # so we do this thing instead
        if time.time() - start < frac_time:
            while (time.time() - start) < frac_time:
                time.sleep(0.001)


def message_dump(player, sleng, tnotes, tickdiv):
    for i in range(sleng):
        t = tnotes[i]
        for m in t:
            if (
                "text" not in m["type"]
                and "_signature" not in m["type"]
                and m["type"]
                not in [
                    "end_of_track",
                    "track_name",
                    "midi_port",
                ]
            ):
                print({k: v for k, v in m.items() if k != "time"})


def main_func(screen):
    out_names = mido.get_output_names()
    # print("Out ports:", out_names)
    selected_midi_out = 1
    # print(out_names[selected_midi_out])
    midi_out = mido.open_output(out_names[selected_midi_out])

    # http://www.ccarh.org/courses/253/handout/gminstruments/
    if True:
        play_song(midi_out, song_length, track_notes, tickdiv, screen)
        # message_dump(midi_out, song_length, track_notes, tickdiv)

    midi_out.close()


# infinite repeat song
while True:
    Screen.wrapper(main_func)
