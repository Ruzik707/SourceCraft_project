import pandas as pd
from scoring.normalizer import calculate_health_score

df = pd.read_csv('repo_health_report.csv')
d = df[df['repo.full_path'] == 'zoyayosyny/zoyayosyny']

# print(calculate_health_score(df))

print(calculate_health_score(d))