# Oscillo Control

Oscillo Control is a browser-based controller for the TEXIO DCS-2204E. The server runs on Linux with Python 3.9 or later and uses only the standard library.

## Getting started

### From the E88 portal

Once the controller is deployed, open **Monitors → Oscilloscope control** from the J-LAN or E16 portal. If prompted, sign in with your existing **E88 DAQ Control** credentials.

### Run the controller directly

Run these commands on a Linux host that can reach the oscilloscopes, such as e88evb01.

```sh
cd /e88/u/e88daq/slow_control/Oscillo_control
python3 server.py
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/) in a browser on the same host. To reach the controller from another PC, run this SSH port forwarding command on that PC.

```sh
ssh -N -L 8765:127.0.0.1:8765 e88daq@10.105.50.22
```

Keep the SSH connection open and navigate to the same URL on that PC.

The default instrument addresses are `192.168.50.128:3000` for Oscilloscope 01 and `192.168.50.129:3000` for Oscilloscope 02. To override their IP addresses or TCP port, use `--scope01`, `--scope02`, and `--device-port` when starting the server. Use `--http-port` to change the port the browser connects to.

## Using the controller

You can view the instrument display and waveforms in viewing mode. Select **Enable control** to change settings, then **Disable control** when you are done. The page starts in viewing mode each time you open it.

- **Instrument display** shows the oscilloscope screen. Turn on **Live display** to refresh it about every 1.5 seconds.
- Select a channel with **CH1** through **CH4**, then use **Show selected channel** to toggle its visibility. To adjust scale or position, scroll over the knob, press `−` or `+`, or enter a value and select **Apply** or press Enter.
- **Run**, **Stop**, and **Single** control acquisition. You can change the trigger source, mode, and level, as well as the slope when using an edge trigger.
- **Waveform samples → Capture CHn** plots samples from acquisition memory. **Download CSV** saves all samples. Time is measured from the first sample, and voltage or current values use the scale and units reported by the instrument.
- If waveform data is unavailable, wait for acquisition to finish on the selected channel and select **Capture** again. Enable waveform headers on the instrument for waveform capture.

See the [Firefox quick-start guide (Japanese)](QUICKSTART.md) for step-by-step instructions.

## Reference

The controller uses the predefined commands for the functions described above. The command reference covers acquisition (section 3-2), channels (3-4), screen output (3-7-9), and acquisition controls, time base, and triggering (3-12 through 3-14). [TEXIO DCS-2000E Programming Manual](https://www.texio.co.jp/uploads/DCS-2000E_B71-0460-01_Programming_J_10.pdf)
