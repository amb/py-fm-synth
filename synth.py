import pyaudio
import numpy as np
import math
import itertools
import mido
import time

block_size = 256
sample_rate = 44100

pyd_instance = pyaudio.PyAudio()
stream = pyd_instance.open(
    rate=sample_rate,
    channels=1,
    format=pyaudio.paInt16,
    output=True,
    frames_per_buffer=block_size,
)

port = mido.open_input()


def note2freq(n):
    return 440.0 * (2 ** ((n - 60) / 12))


class SinOsc:
    def __init__(self, note, velocity):
        # Randomize phase
        self.loc = np.random.randint(22100)
        self.note = note
        self.velocity = velocity

        self.srpi2 = np.pi * 2.0 / sample_rate

    def _getar_simple(self):
        loca, locb = self.loc, self.loc + block_size
        nt = np.arange(loca, locb)
        self.loc += block_size
        return nt

    def render(self):
        nt = self._getar_simple()
        return np.sin(nt * note2freq(self.note) * self.srpi2) * self.velocity

    def render_modulate(self, modulation):
        nt = self._getar_simple()
        return np.sin(nt * note2freq(self.note) * self.srpi2 + modulation) * self.velocity


class ADSR:
    def __init__(self, a, d, s, r):
        self.loc = 0

        asamp = int(a * sample_rate)
        dsamp = int(d * sample_rate)
        rsamp = int(r * sample_rate)

        a_ar = np.arange(0, asamp) / asamp
        d_ar = 1.0 - ((np.arange(0, dsamp) / dsamp) * (1.0 - s))
        self.ad_ar = np.concatenate((a_ar, d_ar))
        self.r_ar = np.arange(0, rsamp) * s / rsamp

        self.sustain = s
        self.note_on = True

        self.previous_point = 0.0

    def render(self):
        loca = self.loc
        locb = self.loc + block_size

        if self.note_on:
            out = self.ad_ar[loca:locb]
            if locb > len(self.ad_ar):
                out = np.concatenate((out, self.sustain * np.ones((locb - len(self.ad_ar),))))
            self.previous_point = out[block_size - 1]
        else:
            # TODO: transitioning to release makes a scratch
            out = self.r_ar[loca:locb]
            if locb > len(self.r_ar):
                out = np.concatenate((out, np.zeros((locb - len(self.r_ar),))))

        self.loc += block_size
        assert len(out) >= block_size

        return out[:block_size]

    def release(self):
        # TODO: transition to release from here (from self.previous_point)
        self.loc = 0
        self.note_on = False

    def is_finished(self):
        return self.note_on == False and self.loc > len(self.r_ar)


class Sound:
    def __init__(self, note, velocity, sample_rate):
        self.sample_rate = sample_rate
        self.note = int(note)
        self.velocity = velocity

        self.adsr = ADSR(0.001, 0.1, 0.4, 0.02)

        self.osc_a = SinOsc(note, velocity)
        self.osc_b = SinOsc(note - 12, 8.0)

        self.active = True
        self.state = "running"

    def render(self):
        adsr = self.adsr.render()

        value = self.osc_a.render_modulate(self.osc_b.render())
        value *= adsr

        if self.state == "released" and self.adsr.is_finished():
            self.active = False

        return value

    def set_state(self, state):
        self.state = state
        self.state_time = time.time()

    def end_playing(self):
        self.adsr.release()
        self.state = "released"


sounds = {}
running = True
while running:
    sample_data = sum(v.render() for k, v in sounds.items())
    # sigmoid = 2.0 / (1.0 + np.exp(-sample_data * 0.5 * 2.0)) - 1.0
    # stream.write(np.int16(sigmoid * 16000.0).tobytes())
    stream.write(np.int16(sample_data * 0.5 * 16000.0).tobytes())

    # read MIDI inputs
    while msg := port.poll():
        if msg.channel >= 0 and msg.channel <= 5:
            print(msg)

            if hasattr(msg, "note"):
                note = int(msg.note)

            if msg.type == "note_off" or (hasattr(msg, "velocity") and msg.velocity == 0):
                if note in sounds:
                    sounds[note].end_playing()

            elif msg.type == "note_on":
                # Div max by 2 (1.0 would be /127)
                sounds[note] = Sound(note, msg.velocity / 127.0, sample_rate)

    # del all notes that have finished
    marked = []
    for k, v in sounds.items():
        if not v.active:
            marked.append(k)
    for m in marked:
        del sounds[m]


stream.stop_stream()
stream.close()

pyd_instance.terminate()

print("fin.")
