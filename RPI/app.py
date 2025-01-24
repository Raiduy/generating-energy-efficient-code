from flask import Flask
from threading import Thread
import usb
import Monsoon.HVPM as HVPM
import Monsoon.sampleEngine as sampleEngine
import Monsoon.Operations as op
import subprocess

V_OUT = 5.1
CAL_TIME = 1250
GRANULARITY = 1

# Monsoon code doesn't work unless it is at the top level.
Mon = HVPM.Monsoon()
Mon.setup_usb(serialno=23170)
Mon.setVout(V_OUT)
engine = sampleEngine.SampleEngine(
    Monsoon=Mon, 
    errorMode=sampleEngine.ErrorHandlingModes.off)
engine.ConsoleOutput(True)

app = Flask(__name__)
measurement_thread = None

def start_measuring(filename):
    # I promise that nobody hates this more than I do. However,
    # when the thread running monsoon is cleaned up, it causes
    # a usb.core.USBError to be thrown within the monsoon code.
    # This in turn causes the monsoon code to detect a reconnect,
    # and restarts the test. The only working solution that doesn't
    # involve celery, is to 'turn off' errors as done above, and
    # catch the USBTimeoutError that is thrown when the thread
    # is cleaned up. 🤢🤢🤢
    global engine
    print(f'Starting sampling for {filename}')
    engine.enableCSVOutput(f"RPI/experiments/blank_experiment/monsoon/{filename}.csv")
    samples = sampleEngine.triggers.SAMPLECOUNT_INFINITE # no limit to samples
    try:
        engine.startSampling(
            calTime=CAL_TIME, 
            granularity=GRANULARITY,
            samples=samples) # try setting to 1
    except usb.core.USBTimeoutError as e:
        pass


@app.post('/start/<filename>')
def start(filename):
    if filename == '':
        return 'Filename not provided', 400

    global engine
    global measurement_thread
    if measurement_thread is None or not measurement_thread.is_alive(): 
        measurement_thread = Thread(target=start_measuring, kwargs={'filename': filename})
        measurement_thread.start()
        return 'OK'

@app.post('/stop')
def stop():
    global engine
    global measurement_thread
    if measurement_thread is not None and measurement_thread.is_alive():
        print('Stopping sampling')
        Mon.stopSampling()
        engine.disableCSVOutput() # Closes and writes the CSV file
        measurement_thread.join()
        measurement_thread = None

        return 'OK'
    else:
        return 'No measurement running', 400


if __name__ == '__main__':
    app.run(host="0.0.0.0")
