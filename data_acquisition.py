# data_acquisition.py
import time
from modbus_control import ModbusDevice
from instrument_control import run_spectrum_test

def measure_eirp(device_ht, device_roll, analyzer_settings, excel_file_path, target_height_mm, target_roll_deg, center_frequency):
    """
    1) 포지셔너(Height, Roll)를 원하는 위치로 이동
    2) 이동 완료 후 스펙트럼 분석기 측정(run_spectrum_test)
    3) EIRP(또는 Channel Power) 결과 반환
    """
    # 높이 축 이동
    device_ht.move_to_target(target_height_mm, True)
    # 롤 축 이동
    device_roll.move_to_target(target_roll_deg, False)
    
    # 이동 완료 대기
    while True:
        completed_ht = device_ht.check_completion(True)
        completed_roll = device_roll.check_completion(False)
        if completed_ht and completed_roll:
            break
        time.sleep(0.5)

    # 스펙트럼 분석기 측정
    channel_power = run_spectrum_test(center_frequency, analyzer_settings, excel_file_path)
    return channel_power
