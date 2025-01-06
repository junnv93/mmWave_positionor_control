# modbus_control.py
import minimalmodbus
import serial
import time
import logging

class ModbusDevice:
    def __init__(self, name, port, address, conversion_factors, has_height=False):
        """
        name: 장비 이름
        port: 시리얼 포트 (예: 'COM3' 또는 '/dev/ttyUSB0')
        address: 모드버스 슬레이브 주소
        conversion_factors: {'height': 값, 'roll': 값} 형태의 딕셔너리 (1mm/1°당 counts)
        has_height: True이면 높이(Height) 축을 지원하는 장비
        """
        self.name = name
        self.port = port
        self.address = address
        self.conversion_factors = conversion_factors
        self.has_height = has_height
        self.instrument = None

    def setup_instrument(self):
        """
        시리얼 포트 초기화 및 장비 설정
        """
        try:
            self.instrument = minimalmodbus.Instrument(self.port, self.address)
            self.instrument.serial.baudrate = 19200
            self.instrument.serial.timeout = 2
            return True
        except Exception as e:
            logging.error(f"{self.name} 장비 설정 오류: {e}")
            return False

    def reset_connection(self):
        """
        재시도 실패 시 연결을 재설정하기 위해 사용
        """
        if self.instrument:
            self.instrument.serial.close()
        time.sleep(0.1)
        return self.setup_instrument()

    def clear_buffer(self):
        """
        오래된 데이터가 남지 않도록 버퍼를 비움
        """
        self.instrument.serial.reset_input_buffer()
        self.instrument.serial.reset_output_buffer()

    def execute_with_retry(self, func, *args, retries=3):
        """
        주어진 함수(func)를 최대 retries번 재시도하여 실행
        """
        for attempt in range(retries):
            try:
                self.clear_buffer()
                result = func(*args)
                time.sleep(0.1)
                return result
            except Exception as e:
                logging.error(f"{self.name} 실행 오류 (시도 {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    logging.info("연결 재설정 중...")
                    self.reset_connection()
                    time.sleep(0.5)
                else:
                    logging.error("최대 재시도 횟수 초과")
                    raise

    def convert_to_real_unit(self, counts, is_height):
        """
        모터 카운트(counts)를 물리적 단위(mm 또는 °)로 변환
        """
        factor = self.conversion_factors["height" if is_height else "roll"]
        return counts / factor

    def convert_to_counts(self, real_unit, is_height):
        """
        물리적 단위(mm 또는 °)를 모터 카운트(counts)로 변환
        """
        factor = self.conversion_factors["height" if is_height else "roll"]
        return int(real_unit * factor)

    def read_location(self, is_height):
        """
        위치 레지스터에서 모터 카운트 읽고, 물리적 단위로 변환
        """
        if is_height and not self.has_height:
            return None
        # 높이(location_ht): 레지스터 0~1, 롤(location_roll): 레지스터 4~5
        register = 0 if is_height else 4
        return self.execute_with_retry(self._read_location, register, is_height)

    def _read_location(self, register, is_height):
        counts = self.instrument.read_long(register, 3, False, 3)
        return self.convert_to_real_unit(counts, is_height)

    def move_to_target(self, target_real_unit, is_height):
        """
        목표 위치(물리 단위)를 입력받아 모터 카운트로 변환 후 이동 시작
        """
        if is_height and not self.has_height:
            logging.warning(f"{self.name}는 높이 축을 지원하지 않습니다.")
            return
        target_counts = self.convert_to_counts(target_real_unit, is_height)
        current_position = self.read_location(is_height)
        if current_position is None:
            logging.error(f"{self.name} 현재 위치 읽기 오류")
            return
        # 타깃 레지스터 (height: 2~3, roll: 6~7), 실제 코드에 맞춰 조정
        target_register = 2 if is_height else 6
        # start 비트 (height: 0, roll: 5)
        start_bit = 0 if is_height else 5
        self.execute_with_retry(self._move_to_target, target_counts, target_register, start_bit)

    def _move_to_target(self, target_counts, target_register, start_bit):
        self.instrument.write_long(target_register, target_counts, False, 3)
        # 모터 구동을 위한 start 비트 On
        self.instrument.write_bit(start_bit, 1, 5)

    def stop_movement(self, is_height):
        """
        긴급정지(stop 비트) 명령
        """
        # stop_ht: 15, stop_roll: 16 → 실제로는 14, 15가 될 수도 있음
        stop_bit = 14 if is_height else 15
        self.execute_with_retry(self.instrument.write_bit, stop_bit, 1, 5)

    def move_up_down(self, is_up):
        """
        수동 조그 기능(Up/Down)
        """
        if not self.has_height:
            logging.warning(f"{self.name}는 높이 축을 지원하지 않습니다.")
            return
        bit = 3 if is_up else 4
        self.execute_with_retry(self.instrument.write_bit, bit, 1, 5)

    def move_cw_ccw(self, is_cw):
        """
        수동 조그 기능(CW/CCW)
        """
        bit = 8 if is_cw else 9
        self.execute_with_retry(self.instrument.write_bit, bit, 1, 5)

    def set_speed(self, speed, is_height):
        """
        속도 레지스터에 1 word 쓰기
        """
        register = 8 if is_height else 9
        self.execute_with_retry(self.instrument.write_register, register, speed, 0, 6, False)

    def enable_movement(self, is_height):
        """
        모터 Enable 비트 읽기
        """
        bit = 1 if is_height else 6
        return self.execute_with_retry(self.instrument.read_bit, bit, 2)

    def check_completion(self, is_height):
        """
        이동 완료 여부 확인
        """
        bit = 2 if is_height else 7
        return self.execute_with_retry(self.instrument.read_bit, bit, 2)

    def check_start_status(self, is_height):
        """
        Start 비트 상태 확인
        """
        bit = 0 if is_height else 5
        return self.execute_with_retry(self.instrument.read_bit, bit, 2)