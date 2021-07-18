import requests
import time
from datetime import datetime
while 1==1:
    print('------------------------------------------------------------------')
    print(datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S"))
    print(f"Upload the farm summary and challenges data to community.chivescoin.org, and you can query the data in this site.")
    content = requests.post('https://community.chivescoin.org/farmerinfor/uploaddata.php', data={'KEY':'KEY','VALUE':'VALUE'}).json()
    print(content)
    time.sleep(600)