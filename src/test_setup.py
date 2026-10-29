import pandas as pd
from faker import Faker

print("Pandas Version:", pd.__version__)

fake = Faker()

print("Employee:", fake.name())

print("Setup Successful")