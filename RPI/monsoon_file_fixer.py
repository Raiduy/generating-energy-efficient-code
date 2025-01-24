import pandas as pd
import os

from scipy import integrate


#EXPERIMENTS = ['canonical', 'baseline', 'blanks', 'guideline', 'keyword', 'platform', 'few-shot', 'human']
EXPERIMENTS = ['few-shot']

def preprocess_monsoon(df):
	index = 0

	while index < len(df):
		repeated_ts = 1
		first_ts = df.loc[index, 'Time(ms)']
		inner_index = index + 1
		while inner_index < len(df) - 1 and first_ts == df.loc[inner_index, 'Time(ms)']:
			repeated_ts += 1
			inner_index += 1

		if repeated_ts > 1:
			ts_delta = df.loc[inner_index, 'Time(ms)'] - df.loc[index, 'Time(ms)']
			increments = ts_delta / repeated_ts
			for i in range(1, repeated_ts):
				df.loc[index + 1, 'Time(ms)'] = first_ts + (i * increments)
		index += 1

	while df.loc[len(df) - 1, 'Time(ms)'] == df.loc[len(df) - 2, 'Time(ms)']:
		df = df.drop(len(df) - 1)
	
	df['TOTAL_ENERGY'] = integrate.trapezoid(df['Power(W)'], df['Time(ms)'])
	return df


if __name__ == '__main__':
	for experiment in EXPERIMENTS:
		for root, dirs, files in os.walk(f'./RPI/{experiment}'):
			total_num = len(files)
			for index, name in enumerate(files):
				if 'preprocessed' in name:
					preproc_path = os.path.join(root, name)
					out_path = preproc_path.replace('preprocessed','fixed')
					if os.path.exists(out_path):
						print(f'Skipped {preproc_path}')
						continue
					print(f'Processing {preproc_path}')
					df = pd.read_csv(preproc_path)
					df = preprocess_monsoon(df)
					df.to_csv(out_path, index=False)

  


# if __name__ == '__main__':
# 	for experiment in EXPERIMENTS:
# 		for root, dirs, files in os.walk(f'./RPI/{experiment}'):
# 			total_num = len(files)
# 			for index, name in enumerate(files):
# 				if 'fixed' in name:
# 					preproc_path = os.path.join(root, name)
# 					#print(f'Processing {preproc_path}')
# 					try:
# 						df = pd.read_csv(preproc_path)
# 						energy = integrate.trapezoid(df['Power(W)'], df['Time(ms)'])
# 						df['TOTAL_ENERGY'] = energy
# 						print(f'{preproc_path} uses {energy} J')
# 						if energy < 0:
# 							print(f'File {preproc_path} has negative values')
# 						df.to_csv(preproc_path, index=False)
# 					except:
# 						print(f'Error {preproc_path}')
					