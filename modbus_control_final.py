#modbus_control.py
import minimalmodbus
import serial
import time
import logging
from enum import Enum
import threading
from typing import Dict, Optional, Union, Callable
from contextlib import nullcontext
from typing import Dict, Optional, Union, Callable, Any

# Constants
TOLERANCE = 0.1  # 위치 허용 오차
DEFAULT_SLAVE_ADDRESS = 233

class PositionerType(Enum):
    ANTENNA_ROLL = "ANT_ROLL"
    ANTENNA_HEIGHT = "ANT_HEIGHT"
    EUT_ROLL = "EUT_ROLL" 
    TURNTABLE_ROLL = "TT_ROLL"

    
class PositionerConstants:
    # 모터 스텝 변환 상수
    STEPS_PER_DEGREE = {
        'ANT_ROLL': 1000,    # Antenna Roll: 1000 steps/degree
        'EUT_ROLL': 80,      # EUT Roll: 80 steps/degree
        'TT_ROLL': 373       # Turntable: 373 steps/degree
    }

    # 동작 범위 제한
    POSITION_LIMITS = {
        'TT_ROLL': {
            'MIN': 0,
            'MAX': 360
        },
        'EUT_ROLL': {
            'MIN': -360,
            'MAX': 360
        },
        'ANT_ROLL': {
            'MIN': 0,
            'MAX': 180
        },
        'ANT_HEIGHT': {
            'MIN': 1520,
            'MAX': 1900
        }
    }

    # 속도 설정
    SPEED_SETTINGS = {
        'TT_ROLL': {
            'DEFAULT': 3000,
            'MAX': 4000
        },
        'EUT_ROLL': {
            'DEFAULT': None,  # 고정 속도
            'MAX': None      # 속도 조절 불가
        },
        'ANT_ROLL': {
            'DEFAULT': 3000,
            'MAX': 5000
        },
        'ANT_HEIGHT': {
            'DEFAULT': 30000,
            'MAX': 37500
        }
    }

    # 높이 관련 상수
    HEIGHT_CONSTANTS = {
        'COUNTS_PER_REV': 800,       # 800 motor counts/rev
        'WORM_REDUCTION': 56,        # 56:1 reduction
        'TRAVEL_PER_TURN': 5,        # 5mm per turn
        'COUNTS_PER_MM': 8960,       # 8960 counts/mm
    }
    
    # 업데이트된 Modbus 레지스터 맵
    REGISTER_MAP = {
        'ANT_HEIGHT': {
            'LOCATION': {'start': 0, 'length': 3},  # 1-2번 주소 (-1 보정)
            'TARGET': {'start': 2, 'length': 3},    # 3-4번 주소 (-1 보정)
            'SPEED': {'start': 8, 'length': 1},     # 9-10번 주소 (-1 보정)
            'START_BIT': 0,           # Modbus Address 1
            'ENABLE_BIT': 1,          # OutBitD3
            'COMPLETE_BIT': 2,        # InBitC3
            'UP_BIT': 3,             # up_ht
            'DOWN_BIT': 4,           # down_ht
            'UPPER_LIMIT_BIT': 11,    # InBitC5
            'LOWER_LIMIT_BIT': 12,    # InBitC6
            'STOP_BIT': 14           # stop_ht
        },
        'ROLL': {  # ANT_ROLL, EUT_ROLL, TT_ROLL 공통
            'LOCATION': {'start': 4, 'length': 3},  # 5-6번 주소 (-1 보정)
            'TARGET': {'start': 6, 'length': 3},    # 7-8번 주소 (-1 보정)
            'SPEED': {'start': 9, 'length': 1},     # 10번 주소 (-1 보정)
            'START_BIT': 5,           # start_roll
            'ENABLE_BIT': 6,          # OutBitE3
            'COMPLETE_BIT': 7,        # InBitB3
            'CW_LIMIT_BIT': 13,       # InBitB5
            'CCW_LIMIT_BIT': 14,      # InBitB6
            'STOP_BIT': 15           # stop_roll
        }
    }

class SharedPortController:
    """공유 포트 제어를 위한 클래스"""
    
    def __init__(self, port: str, slave_address: int = DEFAULT_SLAVE_ADDRESS):
        self.port = port
        self.slave_address = slave_address
        self.lock = threading.RLock()
        self.instrument = self._setup_instrument()

    def _setup_instrument(self) -> Optional[minimalmodbus.Instrument]:  # self.port와 self.slave_address를 사용
        """시리얼 통신 설정"""
        try:
            instrument = minimalmodbus.Instrument(self.port, self.slave_address)  # 클래스 변수 사용
            instrument.serial.baudrate = 19200
            instrument.serial.bytesize = 8
            instrument.serial.parity = serial.PARITY_NONE
            instrument.serial.stopbits = 1
            instrument.serial.timeout = 2
            
            # 시리얼 포트 설정 추가
            instrument.serial.rts = False  # RTS 비활성화
            instrument.serial.dtr = False  # DTR 비활성화
            instrument.serial.xonxoff = False  # Software flow control 비활성화
            
            # 통신 버퍼 클리어
            instrument.serial.reset_input_buffer()
            instrument.serial.reset_output_buffer()
            
            return instrument
        except Exception as e:
            logging.error(f"포트 {self.port} 설정 오류: {e}")
            return None

    def close_connection(self):
        """안전한 연결 종료"""
        try:
            if hasattr(self, 'instrument') and self.instrument is not None:
                try:
                    self.instrument.serial.reset_input_buffer()
                    self.instrument.serial.reset_output_buffer()
                    self.instrument.serial.close()
                except Exception as e:
                    logging.warning(f"SharedPortController 연결 종료 중 오류: {e}")
        except Exception as e:
            logging.error(f"SharedPortController 연결 종료 중 심각한 오류: {e}")

class PositionerController:
    """포지셔너 제어 클래스"""
    
    def __init__(self, positioner_type: PositionerType, port_info: Union[str, SharedPortController], slave_address: int = DEFAULT_SLAVE_ADDRESS):
        self.positioner_type = positioner_type
        self.constants = PositionerConstants()
        
        # ROLL 타입 포지셔너들은 공통 레지스터 맵 사용
        if positioner_type in [PositionerType.ANTENNA_ROLL, PositionerType.EUT_ROLL, PositionerType.TURNTABLE_ROLL]:
            self.reg_map = self.constants.REGISTER_MAP['ROLL']
        else:
            self.reg_map = self.constants.REGISTER_MAP[positioner_type.value]
            
        # 공유 포트 또는 개별 포트 설정
        if isinstance(port_info, SharedPortController):
            self.shared_port = True
            self.port_controller = port_info
            self.instrument = self.port_controller.instrument
        else:
            self.shared_port = False
            self.instrument = minimalmodbus.Instrument(port_info, slave_address)
            self.instrument.serial.baudrate = 19200
            self.instrument.serial.bytesize = 8
            self.instrument.serial.parity = serial.PARITY_NONE
            self.instrument.serial.stopbits = 1
            self.instrument.serial.timeout = 2

        self.position_limits = self.constants.POSITION_LIMITS[positioner_type.value]
        self.speed_settings = self.constants.SPEED_SETTINGS[positioner_type.value]
        
        if self.speed_settings['DEFAULT'] is not None:
            self.set_speed(self.speed_settings['DEFAULT'])
    
    def is_movement_complete(self, target: float) -> bool:
        """위치와 COMPLETE_BIT를 모두 확인하여 이동 완료 여부를 판단"""
        current_pos = self.read_position()
        if current_pos is None:
            return False
            
        position_reached = abs(current_pos - target) < TOLERANCE
        # complete_bit = self.check_completion()
        
        if position_reached:
            logging.debug(f"{self.positioner_type.value} 목표 위치 도달: 현재={current_pos:.2f}, 목표={target:.2f}")
        # if complete_bit:
        #     logging.debug(f"{self.positioner_type.value} COMPLETE_BIT ON")
            
        # return position_reached or complete_bit  # 둘 중 하나라도 True면 이동 완료로 간주

        return position_reached  # 위치만으로 판단

    def is_moving(self, current_pos: float, target: float) -> bool:
        """움직임 여부를 확인"""
        try:
            last_pos = getattr(self, '_last_position', current_pos)
            self._last_position = current_pos
            
            # 위치 변화가 있는지 확인
            position_change = abs(current_pos - last_pos) > 0.01
            # 목표에 도달했는지 확인
            target_reached = abs(current_pos - target) < TOLERANCE
            
            return position_change and not target_reached
            
        except Exception as e:
            logging.error(f"움직임 확인 중 오류: {e}")
            return False

    def check_position_continuously(self, target: float, start_time: float, max_wait_time: float) -> bool:
        current_pos = self.read_position()
        if current_pos is None:
            return False

        # 현재 위치 로깅
        logging.debug(f"{self.positioner_type.value} 현재 위치: {current_pos:.2f}, 목표: {target:.2f}")
        
        # 움직임 멈춤 감지 시 복구 시도
        if not self.is_moving(current_pos, target):
            # START 비트 재설정 시도
            def retry_start(instrument):
                instrument.write_bit(self.reg_map['START_BIT'], 0, 5)
                time.sleep(0.2)
                instrument.write_bit(self.reg_map['START_BIT'], 1, 5)
                return True
                
            self._execute_modbus_command(retry_start)
            
        # 타임아웃 체크
        if time.time() - start_time > max_wait_time:
            logging.error(f"{self.positioner_type.value} 이동 타임아웃")
            return True
            
        return False

    def move_to_position(self, target: float, wait_for_completion: bool = True) -> bool:
        """지정된 위치로 이동"""
        try:
            current_pos = self.read_position()
            if current_pos is None:
                logging.error(f"{self.positioner_type.value} 현재 위치 읽기 실패")
                return False
                
            # 이미 목표 위치에 있는지 확인
            if abs(current_pos - target) < TOLERANCE:
                logging.info(f"{self.positioner_type.value}가 이미 목표 위치({target})에 있습니다.")
                return True
                
            # 타겟 위치 설정
            if not self.set_target_position(target):
                logging.error(f"{self.positioner_type.value} 타겟 위치 설정 실패")
                return False
                
            # 이동 시작
            if not self.start_movement():
                logging.error(f"{self.positioner_type.value} 이동 시작 실패")
                return False
                
            if wait_for_completion:
                max_wait_time = 120  # 최대 대기 시간 (초)
                start_time = time.time()
                last_pos = current_pos
                no_movement_count = 0
                
                while not self.is_movement_complete(target):
                    time.sleep(0.1)
                    
                    # 현재 위치 확인 및 모니터링
                    if self.check_position_continuously(target, start_time, max_wait_time):
                        self.stop_movement()
                        return False
                        
                    # 움직임이 멈췄는지 확인
                    current_pos = self.read_position()
                    if current_pos is not None:
                        if abs(current_pos - last_pos) < TOLERANCE:
                            no_movement_count += 1
                            if no_movement_count > 50:  # 5초 동안 움직임이 없으면
                                logging.error(f"{self.positioner_type.value} 움직임이 멈춤")
                                self.stop_movement()
                                return False
                        else:
                            no_movement_count = 0
                        last_pos = current_pos
                
                # 최종 위치 확인
                final_pos = self.read_position()
                if final_pos is not None:
                    logging.info(f"{self.positioner_type.value} 이동 완료: {final_pos:.2f}")
                    return abs(final_pos - target) < TOLERANCE
                    
            return True
            
        except Exception as e:
            logging.error(f"{self.positioner_type.value} 이동 중 오류 발생: {str(e)}")
            self.stop_movement()
            return False

    def _execute_modbus_command(self, func: Callable, max_retries: int = 3) -> Any:
        """Modbus 명령 실행 래퍼 함수"""
        last_error = None
        for attempt in range(max_retries):
            try:
                with self.port_controller.lock if self.shared_port else nullcontext():
                    instrument = self.port_controller.instrument if self.shared_port else self.instrument
                    if instrument is None:
                        raise Exception("Instrument not initialized")
                        
                    # 통신 설정 재확인
                    instrument.serial.timeout = 1.0  # 짧은 타임아웃 설정
                    instrument.serial.reset_input_buffer()
                    instrument.serial.reset_output_buffer()
                    
                    result = func(instrument)
                    if result is not None or isinstance(result, bool):
                        return result
                        
            except Exception as e:
                last_error = e
                logging.warning(f"통신 시도 {attempt + 1}/{max_retries} 실패: {e}")
                time.sleep(0.2 * (attempt + 1))  # 점진적 대기 시간 증가
                continue
                
        if last_error is not None:
            if "illegal data address" in str(last_error).lower():
                logging.error(f"Modbus 주소 오류: {last_error}")
            else:
                logging.error(f"Modbus 통신 실패: {last_error}")
        return None

    def read_raw_location(self) -> Optional[int]:
        def execute(instrument):
            reg_info = self.reg_map['LOCATION']
            try:
                # 실제 값 읽기
                raw_value = instrument.read_long(reg_info['start'], 3, False, reg_info['length'])                
                return raw_value
            except Exception as e:
                logging.error(f"{self.positioner_type.value} 위치 읽기 실패: {type(e).__name__} - {e}")
                return None
        return self._execute_modbus_command(execute)

    def write_raw_location(self, counts: int) -> bool:
        def execute(instrument):
            reg_info = self.reg_map['LOCATION']
            # 수정: (address, value, functioncode, signed)
            instrument.write_long(reg_info['start'], counts, 3, False)
            return True
        return self._execute_modbus_command(execute)

    def convert_to_counts(self, value: float) -> int:
        if self.positioner_type == PositionerType.ANTENNA_HEIGHT:
            return int(value * self.constants.HEIGHT_CONSTANTS['COUNTS_PER_MM'])
        else:
            return int(value * self.constants.STEPS_PER_DEGREE[self.positioner_type.value])

    def convert_from_counts(self, counts: int) -> float:
        try:
            if self.positioner_type == PositionerType.ANTENNA_HEIGHT:
                return counts / self.constants.HEIGHT_CONSTANTS['COUNTS_PER_MM']  # 8960 counts/mm
            else:
                # Roll 타입에 따른 변환
                steps_per_degree = self.constants.STEPS_PER_DEGREE[self.positioner_type.value]
                return counts / steps_per_degree
        except Exception as e:
            logging.error(f"Count 변환 중 오류 발생: {e}")
            return counts  # 에러 발생시 원래 값 반환

    def read_position(self) -> Optional[float]:
        try:
            raw_counts = self.read_raw_location()
            if raw_counts is not None:
         
                if self.positioner_type == PositionerType.ANTENNA_HEIGHT:
                    # 높이 변환 (8960 counts/mm)
                    mm_value = raw_counts / self.constants.HEIGHT_CONSTANTS['COUNTS_PER_MM']
                    if not (self.position_limits['MIN'] <= mm_value <= self.position_limits['MAX']):
                        logging.warning(f"높이 값이 범위를 벗어남: {mm_value}mm")
                    return mm_value
                else:
                    # 각도 변환
                    steps_per_degree = self.constants.STEPS_PER_DEGREE[self.positioner_type.value]
                    angle = raw_counts / steps_per_degree
                    if not (self.position_limits['MIN'] <= angle <= self.position_limits['MAX']):
                        logging.warning(f"각도 값이 범위를 벗어남: {angle}°")
                    return angle
                
            return None
        except Exception as e:
            logging.error(f"위치 읽기 중 오류 발생: {e}")
            return None

    def read_speed(self) -> Optional[int]:
        """현재 속도를 읽는 함수"""
        def execute(instrument):
            if self.positioner_type == PositionerType.EUT_ROLL:
                return None  # EUT Roll은 속도 설정 불가
                    
            reg_info = self.reg_map['SPEED']
            try:
                logging.debug(f"{self.positioner_type.value} read_speed 파라미터:")
                logging.debug(f"- address (start): {reg_info['start']}")                
                speed = self.instrument.read_register(reg_info['start'])
                logging.debug(f"{self.positioner_type.value} 읽은 speed: {speed} (hex: {hex(speed)})")
                return speed
            except Exception as e:
                logging.error(f"{self.positioner_type.value} 속도 읽기 실패: {e}")
                return None
        return self._execute_modbus_command(execute)

    def determine_shortest_path(self, current_pos: float, target_pos: float) -> float:
        if self.positioner_type == PositionerType.ANTENNA_HEIGHT:
            return target_pos
            
        diff = target_pos - current_pos
        
        if diff > 180:
            return current_pos - (360 - diff)
        elif diff < -180:
            return current_pos + (360 + diff)
        return target_pos

    def set_target_position(self, target: float) -> bool:
        def execute(instrument):            
            current_pos = self.read_position()
            print(f"{self.positioner_type.value} - 현재 위치: {current_pos}")
            if current_pos is None:
                return False
            
            optimized_target = self.determine_shortest_path(current_pos, target)
                
            if not (self.position_limits['MIN'] <= optimized_target <= self.position_limits['MAX']):
                logging.error(
                    f"{self.positioner_type.value} 위치 값 범위 초과: "
                    f"{optimized_target} (허용범위: {self.position_limits['MIN']} ~ {self.position_limits['MAX']})"
                )
                return False

            counts = self.convert_to_counts(optimized_target)

            reg_info = self.reg_map['TARGET']
            instrument.write_long(reg_info['start'], counts, False, 3)
            logging.debug(f"{self.positioner_type.value} target set to: {counts}")

            return True

        return self._execute_modbus_command(execute)

    def set_speed(self, speed: int) -> bool:
        def execute(instrument):
            if self.positioner_type == PositionerType.EUT_ROLL:
                logging.error("EUT Roll은 속도 설정이 불가능합니다")
                return False
                
            if speed > self.speed_settings['MAX']:
                logging.error(
                    f"{self.positioner_type.value} 속도 값 범위 초과: "
                    f"{speed} (최대 허용: {self.speed_settings['MAX']})"
                )
                return False

            reg_info = self.reg_map['SPEED']
            instrument.write_register(reg_info['start'], speed)
            time.sleep(0.5)  # 안정화를 위한 대기

            return True
        return self._execute_modbus_command(execute)

    def start_movement(self) -> bool:
        def execute(instrument):
            try:
                # 먼저 START 비트를 0으로 초기화
                instrument.write_bit(self.reg_map['START_BIT'], 0, 5)
                time.sleep(0.2)
                # 그 다음 1로 설정
                instrument.write_bit(self.reg_map['START_BIT'], 1, 5)
                logging.debug(f"{self.positioner_type.value} movement started")
                return True
            except Exception as e:
                logging.error(f"동작 시작 중 오류: {e}")
                return False
        return self._execute_modbus_command(execute)

    def stop_movement(self) -> bool:
        def execute(instrument):
            try:
                # STOP_BIT 사용하지 않고 START 비트만 초기화
                instrument.write_bit(self.reg_map['START_BIT'], 0, 5)
                time.sleep(0.1)  # 짧은 대기 시간
                return True
            except Exception as e:
                logging.error(f"{self.positioner_type.value} 동작 정지 중 오류: {e}")
                return False
        return self._execute_modbus_command(execute)

    def check_completion(self) -> bool:
        def execute(instrument):
            value = instrument.read_bit(self.reg_map['COMPLETE_BIT'], 2)
            print(f"COMPLETE_BIT read: {value}")
            return bool(value)
        return self._execute_modbus_command(execute)

    def check_limits(self) -> bool:
        def execute(instrument):
            if self.positioner_type == PositionerType.ANTENNA_HEIGHT:
                upper = instrument.read_bit(self.reg_map['UPPER_LIMIT_BIT'], 2)
                lower = instrument.read_bit(self.reg_map['LOWER_LIMIT_BIT'], 2)
                return not (upper or lower)
            else:
                cw = instrument.read_bit(self.reg_map['CW_LIMIT_BIT'], 2)
                ccw = instrument.read_bit(self.reg_map['CCW_LIMIT_BIT'], 2)
                return not (cw or ccw)
        return self._execute_modbus_command(execute)

    # PositionerController 클래스 내에 다음 메소드를 추가
    def close_connection(self):
        """안전한 연결 종료"""
        try:
            # 1. 동작 중지
            self.stop_movement()
            time.sleep(0.2)  # 안정화 대기
            
            # 2. START 비트 초기화
            def reset_start_bit(instrument):
                try:
                    instrument.write_bit(self.reg_map['START_BIT'], 0, 5)
                    return True
                except Exception as e:
                    logging.warning(f"START 비트 초기화 실패: {e}")
                    return False
            self._execute_modbus_command(reset_start_bit)
            
            # 3. 통신 버퍼 정리 (공유 포트가 아닌 경우에만)
            if not self.shared_port and self.instrument is not None:
                try:
                    self.instrument.serial.reset_input_buffer()
                    self.instrument.serial.reset_output_buffer()
                except Exception as e:
                    logging.warning(f"버퍼 초기화 실패: {e}")
                    
        except Exception as e:
            logging.error(f"{self.positioner_type.value} 연결 종료 중 오류: {e}")

    def move_up(self) -> bool:
        if self.positioner_type != PositionerType.ANTENNA_HEIGHT:
            return False
        def execute(instrument):
            return instrument.write_bit(self.reg_map['UP_BIT'], 1, 5)
        return self._execute_modbus_command(execute)

    def move_down(self) -> bool:
        if self.positioner_type != PositionerType.ANTENNA_HEIGHT:
            return False
        def execute(instrument):
            return instrument.write_bit(self.reg_map['DOWN_BIT'], 1, 5)
        return self._execute_modbus_command(execute)

    def calibrate_position(self, value: float) -> bool:
        """현재 위치를 지정된 값으로 보정
        
        Args:
            value (float): 설정할 위치 값 (mm 또는 degree)
            
        Returns:
            bool: 보정 성공 여부
        """
        try:
            # 값 범위 체크
            if not (self.position_limits['MIN'] <= value <= self.position_limits['MAX']):
                logging.error(
                    f"{self.positioner_type.value} 캘리브레이션 값 범위 초과: "
                    f"{value} (허용범위: {self.position_limits['MIN']} ~ {self.position_limits['MAX']})"
                )
                return False
                
            # value를 카운터 값으로 변환
            counts = self.convert_to_counts(value)
            
            def execute(instrument):
                # LOCATION 레지스터에 직접 쓰기
                reg_info = self.reg_map['LOCATION']
                instrument.write_long(reg_info['start'], counts, False,3)
                time.sleep(0.2)  # 안정화 대기
                
                # 쓰기 성공 여부 확인
                read_value = self.read_position()
                if read_value is not None:
                    success = abs(read_value - value) < TOLERANCE
                    if success:
                        logging.info(f"{self.positioner_type.value} 캘리브레이션 완료: {value}")
                    else:
                        logging.error(
                            f"{self.positioner_type.value} 캘리브레이션 실패 - "
                            f"설정값: {value}, 읽은값: {read_value}"
                        )
                    return success
                return False
                    
            return self._execute_modbus_command(execute)
            
        except Exception as e:
            logging.error(f"{self.positioner_type.value} 캘리브레이션 중 오류 발생: {e}")
            return False
        
class MeasurementSystem:
    def __init__(self, ports: Dict[str, str]):
        # Antenna용 공유 포트 컨트롤러 생성
        self.antenna_port_controller = SharedPortController(ports['ANT_ROLL'])  # ANT_ROLL과 ANT_HEIGHT가 같은 포트 사용

        # 포지셔너 컨트롤러 생성
        self.antenna_roll = PositionerController(
            PositionerType.ANTENNA_ROLL, 
            self.antenna_port_controller  # 공유 포트 사용
        )
        self.antenna_height = PositionerController(
            PositionerType.ANTENNA_HEIGHT, 
            self.antenna_port_controller  # 공유 포트 사용
        )
        self.eut_roll = PositionerController(
            PositionerType.EUT_ROLL, 
            ports['EUT_ROLL']  # 개별 포트 사용
        )
        self.turntable_roll = PositionerController(
            PositionerType.TURNTABLE_ROLL, 
            ports['TT_ROLL']  # 개별 포트 사용
        )
        
    def initialize_all(self) -> bool:
        """모든 포트 컨트롤러와 instrument 초기화 상태 확인"""
        return (self.antenna_roll.instrument is not None and 
                self.antenna_height.instrument is not None and 
                self.eut_roll.instrument is not None and 
                self.turntable_roll.instrument is not None)
        
    def move_to_measurement_position(self, 
                                   ant_roll_deg: float,
                                   ant_height_mm: float,
                                   eut_roll_deg: float,
                                   tt_roll_deg: float,
                                   wait_for_completion: bool = True) -> bool:
        try:
            # 순차적 이동 실행
            moves = [
                (self.antenna_roll, ant_roll_deg),
                (self.turntable_roll, tt_roll_deg),
                (self.eut_roll, eut_roll_deg),
                (self.antenna_height, ant_height_mm)  # 높이 먼저 조정

            ]
            
            for controller, target in moves:
                print(f"\n{controller.positioner_type.value} 이동 시작: {target}")
                # 이동 전 통신 상태 확인
                current_pos = controller.read_position()
                if current_pos is None:
                    logging.error(f"{controller.positioner_type.value} 통신 오류")
                    return False
                    
                if not controller.move_to_position(target, wait_for_completion):
                    logging.error(f"{controller.positioner_type.value} 이동 실패")
                    return False
                    
                # 이동 후 대기 시간 추가
                time.sleep(0.5)
            
            return True
            
        except Exception as e:
            logging.error(f"측정 위치 이동 오류: {e}")
            return False
            
    def get_all_positions(self) -> Dict[str, Dict[str, Optional[float]]]:
        return {
            'antenna_roll': {
                'position': self.antenna_roll.read_position(),
                'speed': self.antenna_roll.read_speed()
            },
            'antenna_height': {
                'position': self.antenna_height.read_position(),
                'speed': self.antenna_height.read_speed()
            },
            'eut_roll': {
                'position': self.eut_roll.read_position(),
                'speed': None  # EUT_ROLL은 속도 조절 불가
            },
            'turntable_roll': {
                'position': self.turntable_roll.read_position(),
                'speed': self.turntable_roll.read_speed()
            }
        }

    def cleanup(self):
            """시스템 리소스 정리"""
            try:
                # 1. 모든 동작 정지 (각각 독립적으로 시도)
                for positioner in [self.antenna_roll, self.antenna_height, self.eut_roll, self.turntable_roll]:
                    try:
                        positioner.stop_movement()
                    except Exception as e:
                        logging.warning(f"{positioner.positioner_type.value} 정지 중 오류: {e}")
                
                time.sleep(0.5)  # 충분한 대기 시간
                
                # 2. 시작 비트 초기화 시도 (각각 독립적으로)
                for positioner in [self.antenna_roll, self.antenna_height, self.eut_roll, self.turntable_roll]:
                    try:
                        def reset_start_bit(instrument):
                            instrument.write_bit(positioner.reg_map['START_BIT'], 0, 5)
                            return True
                        positioner._execute_modbus_command(reset_start_bit)
                    except Exception as e:
                        logging.warning(f"{positioner.positioner_type.value} START 비트 초기화 중 오류: {e}")
                
                # 3. 공유 포트 컨트롤러 종료
                if hasattr(self, 'antenna_port_controller') and self.antenna_port_controller is not None:
                    try:
                        self.antenna_port_controller.close_connection()
                    except Exception as e:
                        logging.warning(f"안테나 포트 컨트롤러 종료 중 오류: {e}")
                
                # 4. 개별 포트 컨트롤러 종료
                for positioner in [self.eut_roll, self.turntable_roll]:
                    if not positioner.shared_port and positioner.instrument is not None:
                        try:
                            positioner.instrument.serial.reset_input_buffer()
                            positioner.instrument.serial.reset_output_buffer()
                            positioner.instrument.serial.close()
                        except Exception as e:
                            logging.warning(f"{positioner.positioner_type.value} 포트 종료 중 오류: {e}")
                            
            except Exception as e:
                logging.error(f"Cleanup 중 오류 발생: {e}")
                # 심각한 오류 발생 시 강제 종료 시도
                try:
                    if hasattr(self, 'antenna_port_controller'):
                        if hasattr(self.antenna_port_controller, 'instrument'):
                            if hasattr(self.antenna_port_controller.instrument, 'serial'):
                                self.antenna_port_controller.instrument.serial.close()
                except:
                    pass

    def emergency_stop_all(self) -> None:
        self.antenna_roll.stop_movement()
        self.antenna_height.stop_movement()
        self.eut_roll.stop_movement()
        self.turntable_roll.stop_movement()

    def set_all_speeds(self, speed: int) -> bool:
        success = True
        success &= self.antenna_roll.set_speed(speed)
        success &= self.antenna_height.set_speed(speed)
        success &= self.eut_roll.set_speed(speed)
        success &= self.turntable_roll.set_speed(speed)
        return success

# 사용 예시
if __name__ == "__main__":
    # 로깅 설정
    logging.basicConfig(
        level=logging.DEBUG,  # INFO에서 DEBUG로 변경
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 포트 설정
    ports = {
        'ANT_ROLL': 'COM15',
        'ANT_HEIGHT': 'COM15',
        'EUT_ROLL': 'COM17',
        'TT_ROLL': 'COM12'
    }
    
    # 시스템 초기화
    system = MeasurementSystem(ports)
    if not system.initialize_all():
        logging.error("시스템 초기화 실패")
        exit(1)
        
    try:
        # 초기 위치 확인
        positions = system.get_all_positions()
        print("\n현재 각 포지셔너의 위치와 속도:")
        positions = system.get_all_positions()
        print(f"안테나 높이: {positions['antenna_height']['position']:.2f} mm (속도: {positions['antenna_height']['speed']})")
        print(f"안테나 회전: {positions['antenna_roll']['position']:.2f}° (속도: {positions['antenna_roll']['speed']})")
        print(f"EUT 회전: {positions['eut_roll']['position']:.2f}° (속도: 고정)")
        print(f"턴테이블: {positions['turntable_roll']['position']:.2f}° (속도: {positions['turntable_roll']['speed']})")
        
        # 캘리브레이션 여부 확인
        calibrate = input("\n캘리브레이션을 진행하시겠습니까? (y/n): ").lower().strip()
        
        if calibrate == 'y':
            print("\n각 포지셔너의 허용 범위:")
            print(f"안테나 높이: {PositionerConstants.POSITION_LIMITS['ANT_HEIGHT']['MIN']} ~ {PositionerConstants.POSITION_LIMITS['ANT_HEIGHT']['MAX']} mm")
            print(f"안테나 회전: {PositionerConstants.POSITION_LIMITS['ANT_ROLL']['MIN']} ~ {PositionerConstants.POSITION_LIMITS['ANT_ROLL']['MAX']}°")
            print(f"EUT 회전: {PositionerConstants.POSITION_LIMITS['EUT_ROLL']['MIN']} ~ {PositionerConstants.POSITION_LIMITS['EUT_ROLL']['MAX']}°")
            print(f"턴테이블: {PositionerConstants.POSITION_LIMITS['TT_ROLL']['MIN']} ~ {PositionerConstants.POSITION_LIMITS['TT_ROLL']['MAX']}°")
            
            try:
                # 안테나 높이 캘리브레이션
                height = float(input("\n안테나 높이 캘리브레이션 값 (mm) [-1 입력시 스킵]: "))
                if height != -1:
                    if system.antenna_height.calibrate_position(height):
                        print(f"안테나 높이 캘리브레이션 완료: {height} mm")
                    else:
                        print("안테나 높이 캘리브레이션 실패")
                
                # 안테나 회전 캘리브레이션
                ant_roll = float(input("\n안테나 회전 캘리브레이션 값 (도) [-1 입력시 스킵]: "))
                if ant_roll != -1:
                    if system.antenna_roll.calibrate_position(ant_roll):
                        print(f"안테나 회전 캘리브레이션 완료: {ant_roll}°")
                    else:
                        print("안테나 회전 캘리브레이션 실패")
                
                # EUT 회전 캘리브레이션
                eut_roll = float(input("\nEUT 회전 캘리브레이션 값 (도) [-1 입력시 스킵]: "))
                if eut_roll != -1:
                    if system.eut_roll.calibrate_position(eut_roll):
                        print(f"EUT 회전 캘리브레이션 완료: {eut_roll}°")
                    else:
                        print("EUT 회전 캘리브레이션 실패")
                
                # 턴테이블 캘리브레이션
                tt_roll = float(input("\n턴테이블 캘리브레이션 값 (도) [-1 입력시 스킵]: "))
                if tt_roll != -1:
                    if system.turntable_roll.calibrate_position(tt_roll):
                        print(f"턴테이블 캘리브레이션 완료: {tt_roll}°")
                    else:
                        print("턴테이블 캘리브레이션 실패")
                
                # 캘리브레이션 후 위치 확인
                print("\n캘리브레이션 후 위치:")
                positions = system.get_all_positions()
                print(f"안테나 높이: {positions['antenna_height']['position']:.2f} mm (속도: {positions['antenna_height']['speed']})")
                print(f"안테나 회전: {positions['antenna_roll']['position']:.2f}° (속도: {positions['antenna_roll']['speed']})")
                print(f"EUT 회전: {positions['eut_roll']['position']:.2f}° (속도: 고정)")
                print(f"턴테이블: {positions['turntable_roll']['position']:.2f}° (속도: {positions['turntable_roll']['speed']})")      
            except ValueError:
                print("잘못된 입력입니다. 숫자를 입력해주세요.")
                system.emergency_stop_all()
                exit(1)
        
        print("\n초기화 완료. 시스템 사용 준비가 되었습니다.")
        
        # 측정 위치 이동 여부 확인
        move = input("\n측정 위치로 이동하시겠습니까? (y/n): ").lower().strip()
        
        if move == 'y':
            try:
                print("\n각 포지셔너의 허용 범위:")
                print(f"안테나 높이: {PositionerConstants.POSITION_LIMITS['ANT_HEIGHT']['MIN']} ~ {PositionerConstants.POSITION_LIMITS['ANT_HEIGHT']['MAX']} mm")
                print(f"안테나 회전: {PositionerConstants.POSITION_LIMITS['ANT_ROLL']['MIN']} ~ {PositionerConstants.POSITION_LIMITS['ANT_ROLL']['MAX']}°")
                print(f"EUT 회전: {PositionerConstants.POSITION_LIMITS['EUT_ROLL']['MIN']} ~ {PositionerConstants.POSITION_LIMITS['EUT_ROLL']['MAX']}°")
                print(f"턴테이블: {PositionerConstants.POSITION_LIMITS['TT_ROLL']['MIN']} ~ {PositionerConstants.POSITION_LIMITS['TT_ROLL']['MAX']}°")
                
                # 이동할 위치 입력
                ant_height = float(input("\n안테나 높이 목표 위치 (mm): "))
                ant_roll = float(input("안테나 회전 목표 위치 (도): "))
                eut_roll = float(input("EUT 회전 목표 위치 (도): "))
                tt_roll = float(input("턴테이블 목표 위치 (도): "))
                
                # 속도 설정
                default_speed = input("\n기본 속도를 사용하시겠습니까? (y/n): ").lower().strip()
                if default_speed != 'y':
                    print("\n각 포지셔너의 최대 속도 제한:")
                    print(f"안테나 높이: {PositionerConstants.SPEED_SETTINGS['ANT_HEIGHT']['MAX']}")
                    print(f"안테나 회전: {PositionerConstants.SPEED_SETTINGS['ANT_ROLL']['MAX']}")
                    print(f"턴테이블: {PositionerConstants.SPEED_SETTINGS['TT_ROLL']['MAX']}")
                    speed = int(input("\n설정할 속도 값 입력: "))
                    system.set_all_speeds(speed)
                
                # 측정 위치로 이동
                print("\n측정 위치로 이동을 시작합니다...")
                success = system.move_to_measurement_position(
                    ant_roll_deg=ant_roll,
                    ant_height_mm=ant_height,
                    eut_roll_deg=eut_roll,
                    tt_roll_deg=tt_roll
                )
                
                if success:
                    print("측정 위치 이동 완료")
                    final_positions = system.get_all_positions()
                    print("\n최종 위치:")
                    print(f"안테나 높이: {final_positions['antenna_height']['position']:.2f} mm")
                    print(f"안테나 회전: {final_positions['antenna_roll']['position']:.2f}°")
                    print(f"EUT 회전: {final_positions['eut_roll']['position']:.2f}°")
                    print(f"턴테이블: {final_positions['turntable_roll']['position']:.2f}°")
                else:
                    print("측정 위치 이동 실패")
                    
            except ValueError:
                print("잘못된 입력입니다. 숫자를 입력해주세요.")
                system.emergency_stop_all()
                exit(1)
            
    except Exception as e:
        logging.error(f"실행 중 오류 발생: {e}")
        if system:
            system.emergency_stop_all()
    
    finally:
        if system:
            system.cleanup()
        print("\n프로그램을 종료합니다.")

