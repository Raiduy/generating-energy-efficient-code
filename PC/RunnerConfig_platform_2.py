from EventManager.Models.RunnerEvents import RunnerEvents
from EventManager.EventSubscriptionController import EventSubscriptionController
from ConfigValidator.Config.Models.RunTableModel import RunTableModel
from ConfigValidator.Config.Models.FactorModel import FactorModel
from ConfigValidator.Config.Models.RunnerContext import RunnerContext
from ConfigValidator.Config.Models.OperationType import OperationType
from ProgressManager.Output.OutputProcedure import OutputProcedure as output

from dotenv import load_dotenv
from typing import Dict, List, Any, Optional
from pathlib import Path
from os.path import dirname, realpath

import os
import pandas as pd
import paramiko
import time

class RunnerConfig:
    ROOT_DIR = Path(dirname(realpath(__file__)))

    # ================================ USER SPECIFIC CONFIG ================================
    """The name of the experiment."""
    name:                       str             = "platform/results/2"

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
        
        self.ssh_client = None

        output.console_log("Custom config loaded")

    def create_run_table_model(self) -> RunTableModel:
        """Create and return the run_table model here. A run_table is a List (rows) of tuples (columns),
        representing each run performed"""
        sampling_factor = FactorModel("sampling", [200])

        #llm = FactorModel("llm", ['wizardcoder', 'code-millenials', 'deepseek-coder'])
        llm = FactorModel("llm", ['gpt-4', 'chatgpt', 'speechless-codellama'])
        code = FactorModel("code", ['16', '4', '52', '53', '61', '63', '66', '79', '90'])
        self.run_table_model = RunTableModel(
            factors = [sampling_factor, llm, code],
            exclude_variations = [
                {llm: ['wizardcoder'], code: ['52', '63', '79', '90']},
                {llm: ['code-millenials'], code: []},
                {llm: ['deepseek-coder'], code: ['79']},
                {llm: ['gpt-4'], code: []},
                {llm: ['chatgpt'], code: []},
                {llm: ['speechless-codellama'], code: ['61']},
            ],
            data_columns=['Time (s)', 'AVG_MAX_CPU (%)', 
                          'AVG_USED_MEMORY', 'AVG_USED_SWAP', 
                          'PP0_ENERGY (J)', 'PP1_ENERGY (J)', 
                          'DRAM_ENERGY (J)', 'PACKAGE_ENERGY (J)'],
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
        self.ssh_client=paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_client.connect(hostname=self.TARGET_SYSTEM, username=self.USERNAME, 
                                password=self.PASSWORD)
        print('Connection made!')
        
        self.remote_output_folder = f'{self.OUT_PATH}/{self.name}/{context.run_variation["__run_id"]}'
        _, out, err = self.ssh_client.exec_command(f'mkdir -p {self.remote_output_folder}')
        
        exit_status = out.channel.recv_exit_status()          # Blocking call
        if exit_status == 0:
            print("Output folder created")
        else:
            print(err.readlines())
            print("Error", exit_status)


    def start_measurement(self, context: RunnerContext) -> None:
        """Perform any activity required for starting measurements."""
        sampling_interval = context.run_variation['sampling']
        llm = context.run_variation['llm']
        code = context.run_variation['code']
        experiment = self.name.split('/')[0]
        code_path = f'{self.CODES_PATH}/{experiment}/{llm}/{code}.py'

        print(f'Running {code_path}')

        profiler_cmd = f'sudo -S energibridge \
                        --interval {sampling_interval} \
                        --output {self.remote_output_folder}/energibridge.csv \
                        --summary \
                        python3 {code_path}'

        self.profiler = self.ssh_client.exec_command(profiler_cmd)
        self.profiler[0].write(f'{self.PASSWORD}\n') # stdin


    def interact(self, context: RunnerContext) -> None:
        """Perform any interaction with the running target system here, or block here until the target finishes."""
        pass

    def stop_measurement(self, context: RunnerContext) -> None:
        """Perform any activity here required for stopping measurements."""
        exit_status = self.profiler[1].channel.recv_exit_status() # Blocking call
        if exit_status == 0:
            print('Code executed')
            print(self.profiler[1].readlines()) # stdout
        else:
            print('Error', exit_status)
            print(self.profiler[2].readlines()) # stderr



    def stop_run(self, context: RunnerContext) -> None:
        """Perform any activity here required for stopping the run.
        Activities after stopping the run should also be performed here."""
        print('Pulling remote file...')
        time.sleep(1)
        ftp_client=self.ssh_client.open_sftp()

        try:
            ftp_client.get(f'{self.remote_output_folder}/energibridge.csv',
                           f'{context.run_dir / "energibridge.csv"}')
            print('SUCCESS pulling file')
        except FileNotFoundError as err:
            print(f'FAILED to pull file energibridge.csv not found!')
            _, stdout, _ = self.ssh_client.exec_command(f'ls {self.remote_output_folder}')
            print(f'Folder contents of remote target location are:\n{stdout.readlines()}')

        ftp_client.close()
        self.ssh_client.close()
        print("Connection closed")

    
    def populate_run_data(self, context: RunnerContext) -> Optional[Dict[str, Any]]:
        """Parse and process any measurement data here.
        You can also store the raw measurement data under `context.run_dir`
        Returns a dictionary with keys `self.run_table_model.data_columns` and their values populated"""
        df = pd.read_csv(context.run_dir / "energibridge.csv")

        target_cols = []
        for col in df.columns:
            if 'CPU_USAGE_' in col:
                target_cols.append(col)

        df['MAX_CPU_USAGE'] = df[target_cols].max(axis=1)

        run_data = {
                'Time (s)'            : round((df['Time'].iloc[-1] - df['Time'].iloc[0])/1000, 3),
                'AVG_MAX_CPU (%)'     : round(df['MAX_CPU_USAGE'].mean(), 3),
                'AVG_USED_MEMORY'     : round(df['USED_MEMORY'].mean(), 3),
                'AVG_USED_SWAP'       : round(df['USED_SWAP'].mean(), 3),
                'PP0_ENERGY (J)'      : round(df['PP0_ENERGY (J)'].iloc[-1] - df['PP0_ENERGY (J)'].iloc[0], 3),
                'PP1_ENERGY (J)'      : round(df['PP1_ENERGY (J)'].iloc[-1] - df['PP1_ENERGY (J)'].iloc[0], 3),
                'DRAM_ENERGY (J)'     : round(df['DRAM_ENERGY (J)'].iloc[-1] - df['DRAM_ENERGY (J)'].iloc[0], 3),
                'PACKAGE_ENERGY (J)'  : round(df['PACKAGE_ENERGY (J)'].iloc[-1] - df['PACKAGE_ENERGY (J)'].iloc[0], 3),
        }
        return run_data


    def after_experiment(self) -> None:
        """Perform any activity required after stopping the experiment here
        Invoked only once during the lifetime of the program."""
        pass

    # ================================ DO NOT ALTER BELOW THIS LINE ================================
    experiment_path:            Path             = None
