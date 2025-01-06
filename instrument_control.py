# instrument_control.py
import time
import logging
import sys
import pyvisa
import pandas as pd

# test_utils 모듈에서 재활용할 함수 임포트
from test_utils import read_gpib_addresses, read_save_data, open_instrument, logger

##############################################################################
# 공통 함수: 스펙트럼 분석기 동작 대기, 풀스크린 토글 등
##############################################################################

def wait_for_operation_complete(device):
    """
    스펙트럼 분석기에 대기 명령 (*WAI)을 보내고,
    내부적으로 동작이 완료될 때까지 기다리는 함수입니다.
    """
    device.write('*WAI')
    
def safe_query(device, query, default=0.0):
    try:
        response = device.query(query)
        return float(response)
    except ValueError:
        logger.warning(f"Invalid response received for query '{query}'. Defaulting to {default}")
        return default

def toggle_full_screen(device):
    """
    스펙트럼 분석기의 현재 디스플레이 모드를 확인하고,
    Full Screen 모드가 OFF라면 ON으로 전환합니다.
    """
    current_state = device.query(':DISP:FSCR:STAT?').strip()
    if current_state == '0':
        device.write('DISP:FSCR ON')
        print("Full Screen mode has been turned ON.")
    else:
        print("Full Screen mode is already ON.")

##############################################################################
# 스펙트럼 분석기 초기화 함수
##############################################################################

def initialize_analyzer(device, analyzer_settings):
    """
    분석기(Analyzer)를 초기화하고,
    주어진 Analyzer Settings에 맞춰 기본 설정을 적용합니다.
    """
    device.write('*RST')
    device.write('*CLS')
    device.write(':SYST:DISP:UPD ON')
    device.write(':INIT:CONT OFF')
    # 트랜스듀서 보정
    transducer = analyzer_settings.get('Transducer')
    if transducer:
        device.write(f":SENS:CORR:TRAN:SEL '{transducer}'")
        device.write(f":SENS:CORR:TRAN:STAT ON")
    # 오프셋 레벨
    offset_level = analyzer_settings.get('Offset Level', 0)
    device.write(f":DISP:WIND:TRAC:Y:SCAL:RLEV:OFFS {offset_level}")

##############################################################################
# 메인 측정 함수 (avgEIRP.py 내용을 통합)
##############################################################################

def run_spectrum_test(center_frequency, analyzer_settings, file_path):
    """
    avgEIRP.py의 run_test() 내용을 참고하여 만든 스펙트럼 분석기 측정 함수입니다.
    - center_frequency: 측정할 주파수(Hz 단위)
    - analyzer_settings: 딕셔너리 형태로 필요한 스펙트럼 분석기 파라미터
    - file_path: 엑셀(Chamber Config, Save Data) 등이 위치한 파일 경로

    반환값: channel_power (단위: dBm)
    """
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        stream=sys.stdout)

    # 1) GPIB 주소 및 User ID 가져오기
    gpib_addresses = read_gpib_addresses(file_path)
    analyzer_gpib_addr = gpib_addresses.get('Analyzer GPIB', '18')  # 기본값 18
    pxa_address = f"TCPIP0::{analyzer_gpib_addr}::inst0::INSTR"

    save_data = read_save_data(file_path)
    user_id = save_data.get('User ID', 'Unknown')

    # 2) 스펙트럼 분석기 연결
    rm = pyvisa.ResourceManager()
    pxa = open_instrument(pxa_address, rm)
    
    if not pxa:
        logging.error("Failed to establish connection with the spectrum analyzer.")
        return None

    channel_power = None

    try:
        # 3) Analyzer 초기화
        initialize_analyzer(pxa, analyzer_settings)

        # 4) 사용자명(세션명) 설정
        pxa.write(f":INST:REN 'Spectrum','{user_id}'")

        # Occupied Bandwidth 설정 (ACP 모드 활용)
        pxa.write(':CALC:MARK:FUNC:POW:SEL ACP')
        pxa.write(':SENS:POW:ACH:ACP 0')

        # 5) 감쇠(Attenuation)
        ref_level_setting = analyzer_settings.get('Reference Level', 'AUTO')
        attenuation_value = analyzer_settings.get('Attenuation', 'AUTO')
        if attenuation_value == 'AUTO':
            attenuation_cmd = ':INP:ATT:AUTO ON'
            print('ATT AUTO')
        else:
            pxa.write(':INP:ATT:AUTO OFF')
            attenuation_cmd = f':INP:ATT {attenuation_value}'
        pxa.write(attenuation_cmd)

        # 6) 레퍼런스 레벨 설정
        if isinstance(ref_level_setting, str) and ref_level_setting.upper() == 'AUTO':
            pxa.write(':DISP:WIND:TRAC:Y:SCAL:RLEV 40')  # 임시로 40 dBm 설정
        else:
            pxa.write(f':DISP:WIND:TRAC:Y:SCAL:RLEV {ref_level_setting}')

        # 7) 주파수 및 스팬 설정
        pxa.write(f':SENS:FREQ:CENT {center_frequency}')
        pxa.write(f':SENS:FREQ:SPAN {analyzer_settings.get("Span", 100e6)}')
        wait_for_operation_complete(pxa)

        # 8) 프리앰프 설정
        if analyzer_settings.get('Preamp') == 'ON':
            pxa.write(':INP:GAIN:STAT ON')
            pxa.write(':INP:GAIN:VAL ON')

        # 9) RBW / VBW
        pxa.write(f':SENS:BAND:RES {analyzer_settings.get("RBW", 1e6)}')
        pxa.write(f':SENS:BAND:VID {analyzer_settings.get("VBW", 3e6)}')

        # 10) 트레이스 / 디텍터
        pxa.write(f':DISP:WIND:SUBW:TRAC1:MODE {analyzer_settings.get("Trace Mode", "WRIT")}')
        pxa.write(f':SENS:WIND:DET1:FUNC {analyzer_settings.get("Average Type", "POIN")}')
        pxa.write(f':SENS:AVER:TYPE {analyzer_settings.get("Det Type", "MAXH")}')
        pxa.write(f':SENS:POW:ACH:BWID:CHAN1 {analyzer_settings.get("Channel Bandwidth", 20e6)}')
        pxa.write(attenuation_cmd)  # 재설정 (혹시 중간에 재작성 필요)

        # 11) 스윕 타임
        sweep_time = analyzer_settings.get('Sweep Time', 'AUTO')
        if sweep_time == 'AUTO':
            pxa.write(':SENS:SWE:TIME:AUTO ON')
        else:
            pxa.write(':SENS:SWE:TIME:AUTO OFF')
            pxa.write(f':SENS:SWE:TIME {sweep_time}')

        # 스윕 포인트, 횟수
        pxa.write(f':SENS:SWE:WIND:POIN {analyzer_settings.get("Sweep Points", 1001)}')
        sweep_counts = analyzer_settings.get("Sweep Counts", 5)

        # 12) REF Level이 AUTO라면, 먼저 Rough Sweep으로 Peak 체크
        if isinstance(ref_level_setting, str) and ref_level_setting.upper() == 'AUTO':
            pxa.write(f':SENS:SWE:COUN 10')
            pxa.write(':INIT:IMM;*WAI')
            pxa.write('CALC:MARK1:MAX:PEAK')
            pxa.write('CALC:MARK1:STAT ON')
            wait_for_operation_complete(pxa)

            peak_level = safe_query(pxa, 'CALC:MARK1:Y?', default=0.0)
            print(f"Initial Peak Level: {peak_level}")

            if isinstance(peak_level, float):
                adjusted_level = peak_level + 20
                print(f"Adjusted Level: {adjusted_level}")
                ref_level = f'{adjusted_level}'
            else:
                ref_level = '30'
                print(f"Peak level invalid, set default ref level to {ref_level}")
        else:
            ref_level = f'{ref_level_setting}'
            peak_level = None

        # 조정된 Ref Level 적용
        pxa.write(f':DISP:WIND:TRAC:Y:SCAL:RLEV {ref_level}')
        pxa.write(f':SENS:SWE:COUN {sweep_counts}')

        # 13) 최종 스윕 실행
        pxa.write(':INIT:IMM;*WAI')
        pxa.write('CALC:MARK:AOFF')
        wait_for_operation_complete(pxa)

        # 14) 채널 파워 읽기
        while True:
            channel_power_str = pxa.query('CALC:MARK:FUNC:POW:RES? CPOW').strip()
            if channel_power_str:
                try:
                    channel_power = round(float(channel_power_str), 4)
                    break
                except ValueError:
                    print(f"Invalid channel power value: {channel_power_str}")
            else:
                time.sleep(0.1)

        # 필요하다면 추가 대기
        wait_for_operation_complete(pxa)
        wait_time = analyzer_settings.get("Wait Time", 1)
        time.sleep(wait_time)
        wait_for_operation_complete(pxa)

        print(f"Channel power: {channel_power} dBm")

    except pyvisa.VisaIOError as e:
        print(f"An error occurred during communication with the spectrum analyzer: {e}")
    finally:
        pxa.close()
        print("Connection to the spectrum analyzer has been closed.")

    return channel_power