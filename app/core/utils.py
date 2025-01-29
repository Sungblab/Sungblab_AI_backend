from datetime import datetime
import pytz

KST = pytz.timezone('Asia/Seoul')

def get_kr_time():
    return datetime.now(KST) 