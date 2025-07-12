import uuid
from datetime import datetime, timezone
import pytz

def generate_uuid():
    return str(uuid.uuid4())

KST = pytz.timezone('Asia/Seoul')

def get_kr_time():
    """현재 UTC 시간을 한국 시간(KST)으로 변환하여 반환합니다.
    
    주의: 이 함수는 사용자에게 시간을 표시할 때만 사용해야 합니다.
    데이터베이스에 저장할 때는 항상 UTC를 사용하세요.
    """
    return datetime.now(timezone.utc).astimezone(KST)

def to_utc_from_kst(dt: datetime) -> datetime:
    """KST 시간을 UTC 시간으로 변환합니다."""
    if dt.tzinfo is None:
        dt = KST.localize(dt) # naive datetime을 KST로 지역화
    return dt.astimezone(timezone.utc)

def to_kst_from_utc(dt: datetime) -> datetime:
    """UTC 시간을 KST 시간으로 변환합니다."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc) # naive datetime을 UTC로 가정
    return dt.astimezone(KST) 