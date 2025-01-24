from EventManager.Models.RunnerEvents import RunnerEvents
from EventManager.EventSubscriptionController import EventSubscriptionController
from ConfigValidator.Config.Models.RunTableModel import RunTableModel
from ConfigValidator.Config.Models.FactorModel import FactorModel
from ConfigValidator.Config.Models.RunnerContext import RunnerContext
from ConfigValidator.Config.Models.OperationType import OperationType
from ProgressManager.Output.OutputProcedure import OutputProcedure as output

from dotenv import load_dotenv
from os.path import dirname, realpath
from pathlib import Path
from scipy import integrate
from typing import Dict, List, Any, Optional

import os
import pandas as pd
import paramiko
import re
import requests
import time

def parse_sar_file(filepath: str):
    try:
        with open(filepath, 'r') as f:
            data = f.read().splitlines(True)
            if len(data) < 5:
                print('ERROR: Sar file does not have enough data')
                return
            data[2] = re.sub(r'[^\S\r\n]+', ',', data[2])
            data[2] = data[2].replace(data[2].split(',')[0], 'Time (s)')

            for i in range(3, len(data) - 1):
                data[i] = re.sub(r'[^\S\r\n]+', ',', data[i])
                timestamp = data[i].split(',')[0]
                h, m, s = timestamp.split(':')
                seconds = int(h) * 3600 + int(m) * 60 + int(s)
                data[i] = data[i].replace(timestamp, str(seconds))
            new_filepath = filepath.replace('sar_log.txt', 'sar_log.csv')
            with open(new_filepath, 'w') as o:
                o.writelines(data[2:len(data) - 1])
                print('Successfully parsed sar file!')
    except FileNotFoundError:
        print(f'Error parsing sar file:\n{filepath} does not exist!')

def parse_monsoon_file(filepath: str):
    try:
        df = pd.read_csv(filepath)
        df = df.drop('Unnamed: 3', axis=1)

        df['Time(ms)'] = df['Time(ms)'].str.split('(').str[1].str.split(')').str[0].astype(float)
        df['Main(mA)'] = df['Main(mA)'].str.split('(').str[1].str.split(')').str[0].astype(float)
        df['Main Voltage(V)'] = df['Main Voltage(V)'].str.split('(').str[1].str.split(')').str[0].astype(float)

        df['Power(W)'] = df['Main(mA)'] * df['Main Voltage(V)']
        df.to_csv(filepath.replace('monsoon', 'monsoon_preprocessed'), index=False)
    except FileNotFoundError:
        print(f'Error parsing monsoon file:\n{filepath} does not exist!')


class RunnerConfig:
    ROOT_DIR = Path(dirname(realpath(__file__)))

    # ================================ USER SPECIFIC CONFIG ================================
    """The name of the experiment."""
    name:                       str             = "blanks/results/2"

    """The path in which Experiment Runner will create a folder with the name `self.name`, in order to store the
    results from this experiment. (Path does not need to exist - it will be created if necessary.)
    Output path defaults to the config file's path, inside the folder 'experiments'"""
    results_output_path:        Path             = ROOT_DIR 

    """Experiment operation type. Unless you manually want to initiate each run, use `OperationType.AUTO`."""
    operation_type:             OperationType   = OperationType.AUTO

    """The time Experiment Runner will wait after a run completes.
    This can be essential to accommodate for cooldown periods on some systems."""
    time_between_runs_in_ms:    int             = 60000
    


    # Dynamic configurations can be one-time satisfied here before the program takes the config as-is
    # e.g. Setting some variable based on some criteria
    def __init__(self):
        """Executes immediately after program start, on config load"""

        EventSubscriptionController.subscribe_to_multiple_events([
            (RunnerEvents.BEFORE_EXPERIMENT, self.before_experiment),
            (RunnerEvents.BEFORE_RUN       , self.before_run       ),
            (RunnerEvents.START_RUN        , self.start_run        ),
            (RunnerEvents.START_MEASUREMENT, self.start_measurement),
            (RunnerEvents.INTERACT         , self.interact         ),
            (RunnerEvents.STOP_MEASUREMENT , self.stop_measurement ),
            (RunnerEvents.STOP_RUN         , self.stop_run         ),
            (RunnerEvents.POPULATE_RUN_DATA, self.populate_run_data),
            (RunnerEvents.AFTER_EXPERIMENT , self.after_experiment )
        ])
        self.run_table_model = None  # Initialized later

        load_dotenv()
        parallel_id = self.name.split('/')[2]
        print('PLL ID:', parallel_id)
        self.TARGET_SYSTEM  = os.getenv(f'SYS{parallel_id}')
        self.USERNAME       = os.getenv('USERNAME')
        self.PASSWORD       = os.getenv('PASSWORD')
        self.CODES_PATH     = os.getenv('CODES_PATH')
        self.OUT_PATH       = os.getenv('OUT_PATH')
        
        self.SERVER_HOST            = os.getenv(f'SERVER_HOST_{parallel_id}')
        self.SERVER_HOST_PORT       = os.getenv('SERVER_HOST_PORT')
        self.SERVER_HOST_USERNAME   = os.getenv(f'SERVER_HOST_{parallel_id}_USERNAME')
        self.SERVER_HOST_PASSWORD   = os.getenv(f'SERVER_HOST_{parallel_id}_PASSWORD')
        self.SERVER_HOST_PATH       = os.getenv(f'SERVER_HOST_{parallel_id}_PATH')
        
        self.ssh_client_target = None

        output.console_log("Custom config loaded")

    def create_run_table_model(self) -> RunTableModel:
        """Create and return the run_table model here. A run_table is a List (rows) of tuples (columns),
        representing each run performed"""
        sampling_factor = FactorModel("sampling", [200])

        #llm = FactorModel("llm", ['wizardcoder', 'code-millenials', 'deepseek-coder'])
        #llm = FactorModel("llm", ['gpt-4', 'chatgpt', 'speechless-codellama'])
        llm = FactorModel("llm", [''])
        code = FactorModel("code", ['63', '66', '79', '90'])
        self.run_table_model = RunTableModel(
            factors = [sampling_factor, llm, code],
            data_columns = ['Time sar (s)', 'Time mns (s)', 
                            'AVG_MAX_CPU (%)', 'AVG_POWER (W)', 
                            'ENERGY (J)'],
            repetitions=21,
        )
        return self.run_table_model

    def before_experiment(self) -> None:
        """Perform any activity required before starting the experiment here
        Invoked only once during the lifetime of the program."""
        pass

    def before_run(self) -> None:
        """Perform any activity required before starting a run.
        No context is available here as the run is not yet active (BEFORE RUN)"""
        pass

    def start_run(self, context: RunnerContext) -> None:
        """Perform any activity required for starting the run here.
        For example, starting the target system to measure.
        Activities after starting the run should also be performed here."""
        self.ssh_client_target = paramiko.SSHClient()
        self.ssh_client_target.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_client_target.connect(hostname=self.TARGET_SYSTEM, username=self.USERNAME, 
                                password=self.PASSWORD)
        print('Target connection established!')
        
        self.remote_output_folder = f'{self.OUT_PATH}/{self.name}/{context.run_variation["__run_id"]}'
        _, out, err = self.ssh_client_target.exec_command(f'mkdir -p {self.remote_output_folder}')
        
        exit_status = out.channel.recv_exit_status()          # Blocking call
        if exit_status == 0:
            print("Output folder created")
        else:
            print(err.readlines())
            print("Error", exit_status)
        
        llm = context.run_variation['llm']
        code = context.run_variation['code']
        experiment = self.name.split('/')[0]
        #code_path = f'{self.CODES_PATH}/{experiment}/{llm}/{code}.py'
        code_path = f'{self.CODES_PATH}/{experiment}/{code}.py'
        print(f'Running {code_path}')

        code_cmd = f'experiments/.exp-venv/bin/python3 {code_path}'
        sar_cmd = f'sar -A -o {self.remote_output_folder}/sar_log.file 1 800'
        
        pi_cmd = f"parallel -j2 --halt now,success=1 ::: '{code_cmd}' '{sar_cmd}'"
        self.target = self.ssh_client_target.exec_command(pi_cmd)


    def start_measurement(self, context: RunnerContext) -> None:
        """Perform any activity required for starting measurements."""
        output.console_log("Starting measurement on the dev computer...")
        
        self.server_output_path = f'{self.name}/{context.run_variation["__run_id"]}'

        res = requests.post(f'http://{self.SERVER_HOST}:{self.SERVER_HOST_PORT}/start/{self.server_output_path}', \
                            json={}, headers={'Content-Type': 'application/json'})
        output.console_log(res.text)


    def interact(self, context: RunnerContext) -> None:
        """Perform any interaction with the running target system here, or block here until the target finishes."""
        pass


    def stop_measurement(self, context: RunnerContext) -> None:
        """Perform any activity here required for stopping measurements."""
        output.console_log("Stopping measurement on the dev computer...")

        # Wait for code to finish running
        exit_status = self.target[1].channel.recv_exit_status()          # Blocking call
        if exit_status == 0:
            print(self.target[1].readlines())
            print("Code run completed.")
        else:
            print(self.target[2].readlines())
            print("Error", exit_status)
        
        # Stop Monsoon from measuring
        res = requests.post(f'http://{self.SERVER_HOST}:{self.SERVER_HOST_PORT}/stop', json={}, headers={'Content-Type': 'application/json'})
        output.console_log(res.text)

        output.console_log("Config.stop_measurement called!")

    def stop_run(self, context: RunnerContext) -> None:
        """Perform any activity here required for stopping the run.
        Activities after stopping the run should also be performed here."""
        print('Creating readable sar file...')
        utils = self.ssh_client_target.exec_command(f'sar -f {self.remote_output_folder}/sar_log.file \
                                                              > {self.remote_output_folder}/sar_log.txt')
        if utils[1].channel.recv_exit_status() == 0:
            print(utils[1].readlines())
            print('Readable sar file created!')
        else:
            print(utils[2].readlines())
            print('Error creating sar file!')
        
        print('Pulling readable sar file...')
        ftp_client_pi = self.ssh_client_target.open_sftp()
        try:
            ftp_client_pi.get(f'{self.remote_output_folder}/sar_log.txt',
                              f'{context.run_dir / "sar_log.txt"}')
            while not os.path.exists(context.run_dir / 'sar_log.txt'):
                continue
            print('SUCCESS sar file pulled!')
        except FileNotFoundError as err:
            print(f'FAILED to pull file energibridge.csv not found!')
            _, stdout, _ = self.ssh_client_target.exec_command(f'ls {self.remote_output_folder}')
            print(f'Folder contents of remote target location are:\n{stdout.readlines()}')

        print('Closed connections to Raspberry! Preprocessing sar file...')
        time.sleep(3)

        print('Establishing connection to SERVER_HOST!')
        self.ssh_server = paramiko.SSHClient()
        self.ssh_server.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_server.connect(hostname=self.SERVER_HOST, username=self.SERVER_HOST_USERNAME, 
                                password=self.SERVER_HOST_PASSWORD)
        print('Connection made!')

        server_host_folder = f'{self.SERVER_HOST_PATH}/{self.server_output_path}'
        print('Pulling Monsoon file...')
        ftp_client_server = self.ssh_server.open_sftp()
        try:
            ftp_client_server.get(f'{server_host_folder}/monsoon.csv',
                              f'{context.run_dir / "monsoon.csv"}')
            while not os.path.exists(f'{context.run_dir}/monsoon.csv'):
                continue
            print('SUCCESS Monsoon file pulled!')
        except FileNotFoundError as err:
            print(f'FAILED to pull file monsoon.csv not found!')
            _, stdout, _ = self.ssh_server.exec_command(f'dir {server_host_folder}')
            print(f'Folder contents of remote target location are:\n{stdout.readlines()}')

        time.sleep(10)
        parse_sar_file(f'{context.run_dir / "sar_log.txt"}')
        parse_monsoon_file(f'{context.run_dir}/monsoon.csv')

        ftp_client_pi.close()
        ftp_client_server.close()
        self.ssh_client_target.close()
        self.ssh_server.close()

    def populate_run_data(self, context: RunnerContext) -> Optional[Dict[str, Any]]:
        """Parse and process any measurement data here.
        You can also store the raw measurement data under `context.run_dir`
        Returns a dictionary with keys `self.run_table_model.data_columns` and their values populated"""
        sar_time = -1
        mns_time = -1
        avg_max_cpu = -1
        avg_pwr = -1
        eng = -1

        if os.path.exists(context.run_dir / 'sar_log.csv'):
            df_sar = pd.read_csv(context.run_dir / "sar_log.csv")
            sar_time = df_sar['Time (s)'].iloc[-1] - df_sar['Time (s)'].iloc[0]
            avg_max_cpu = df_sar['%user'].mean()

        if os.path.exists(context.run_dir / 'monsoon_preprocessed.csv'):
            df_monsoon = pd.read_csv(context.run_dir / "monsoon_preprocessed.csv")
            mns_time = df_monsoon['Time(ms)'].iloc[-1] - df_monsoon['Time(ms)'].iloc[0]
            avg_pwr = df_monsoon['Power(W)'].mean()
            eng = integrate.trapezoid(df_monsoon['Time(ms)'], df_monsoon['Power(W)'])

        run_data = {
                'Time sar (s)'      : sar_time,
                'Time mns (s)'      : round(mns_time, 3),
                'AVG_MAX_CPU (%)'   : round(avg_max_cpu, 3),
                'AVG_POWER (W)'     : round(avg_pwr, 3),
                'ENERGY (J)'        : round(eng, 3),
        }

        return run_data


    def after_experiment(self) -> None:
        """Perform any activity required after stopping the experiment here
        Invoked only once during the lifetime of the program."""
        pass


# ================================ DO NOT ALTER BELOW THIS LINE ================================
    experiment_path:            Path             = None
