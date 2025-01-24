import pandas as pd

FILEPATH = './RPI/few-shot/results/2/run_10_repetition_3/monsoon.csv'

if __name__=='__main__':
  df = pd.read_csv(FILEPATH)
  df = df.drop('Unnamed: 3', axis=1)

  df['Time(ms)'] = df['Time(ms)'].str.split('(').str[1].str.split(')').str[0].astype(float)
  df['Main(mA)'] = df['Main(mA)'].str.split('(').str[1].str.split(')').str[0].astype(float)
  df['Main Voltage(V)'] = df['Main Voltage(V)'].str.split('(').str[1].str.split(')').str[0].astype(float)

  df['Power(W)'] = df['Main(mA)'] * df['Main Voltage(V)']
  df.to_csv(FILEPATH.replace('monsoon', 'monsoon_preprocessed'), index=False)
