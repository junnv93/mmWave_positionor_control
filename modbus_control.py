import minimalmodbus
import serial
import time
import logging
from enum import Enum
from typing import Dict, Optional, Union
import math

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
    
    # 높이 관련 상수
    HEIGHT_CONSTANTS = {
        'COUNTS_PER_REV': 800,       # 800 motor counts/rev
        'WORM_REDUCTION': 56,        # 56:1 reduction
        'TRAVEL_PER_TURN': 5,        # 5mm per turn
        'COUNTS_PER_MM': 8960,       # 8960 counts/mm
        'MAX_HEIGHT_MM': 1900,       # 최대 1900mm
        'MIN_HEIGHT_MM': 0
    }
    
    # Modbus 레지스터 맵 - 문서 기반으로 수정
    REGISTER_MAP = {
        'ANT_ROLL': {
            'LOCATION': 0,            # 2 registers for location
            'TARGET': 2,              # 2 registers for target
            'START_BIT': 0,           # Modbus Address 1
            'COMPLETE_BIT': 2,        # Modbus Address 3
            'UP_BIT': 3,             # OutBitD3
            'DOWN_BIT': 4,           # OutBitD4
            'STOP_BIT': 14,          # Stop command
            'CW_LIMIT_BIT': 4,       # B5
            'CCW_LIMIT_BIT': 5       # B6
        },
        'ANT_HEIGHT': {
            'LOCATION': 0,            # 2 registers for location
            'TARGET': 2,              # 2 registers for target
            'START_BIT': 0,           # Modbus Address 1
            'COMPLETE_BIT': 2,        # Modbus Address 3
            'UP_BIT': 3,             # OutBitD3
            'DOWN_BIT': 4,           # OutBitD4
            'STOP_BIT': 14,          # Stop command
            'UPPER_LIMIT_BIT': 4,    # C5
            'LOWER_LIMIT_BIT': 5     # C6
        },
        'EUT_ROLL': {
            'LOCATION': 0,
            'TARGET': 2,
            'START_BIT': 0,
            'COMPLETE_BIT': 2,
            'CW_LIMIT_BIT': 4,
            'CCW_LIMIT_BIT': 5,
            'STOP_BIT': 14
        },
        'TT_ROLL': {
            'LOCATION': 0,
            'TARGET': 2,
            'START_BIT': 0,
            'COMPLETE_BIT': 2,
            'CW_LIMIT_BIT': 4,
            'CCW_LIMIT_BIT': 5,
            'STOP_BIT': 14
        }
    }

class PositionerController:
    def __init__(self, positioner_type: PositionerType, port: str, slave_address: int = 233):
        """포지셔너 컨트롤러 초기화"""
        self.positioner_type = positioner_type
        self.port = port
        self.slave_address = slave_address
        self.instrument = None
        self.constants = PositionerConstants()
        self.reg_map = self.constants.REGISTER_MAP[positioner_type.value]
        self.setup_instrument()
        
    def setup_instrument(self) -> bool:
        """Modbus 통신 설정"""
        try:
            self.instrument = minimalmodbus.Instrument(self.port, self.slave_address)
            self.instrument.serial.baudrate = 19200
            self.instrument.serial.bytesize = 8
            self.instrument.serial.parity = serial.PARITY_NONE
            self.instrument.serial.stopbits = 1
            self.instrument.serial.timeout = 2
            return True
        except Exception as e:
            logging.error(f"{self.positioner_type.value} 설정 오류: {e}")
            return False

    def read_raw_location(self) -> Optional[int]:
        """현재 위치 Raw 값 읽기"""
        try:
            return self.instrument.read_long(0, False, 3)
        except Exception as e:
            logging.error(f"위치 읽기 오류: {e}")
            return None

    def write_raw_location(self, counts: int) -> bool:
        """현재 위치 Raw 값 쓰기"""
        try:
            self.instrument.write_long(0, counts, False, 3)
            return True
        except Exception as e:
            logging.error(f"위치 쓰기 오류: {e}")
            return False

    def convert_to_counts(self, value: float) -> int:
        """실제 단위를 모터 카운트로 변환"""
        if self.positioner_type == PositionerType.ANTENNA_HEIGHT:
            return int(value * self.constants.HEIGHT_CONSTANTS['COUNTS_PER_MM'])
        else:
            return int(value * self.constants.STEPS_PER_DEGREE[self.positioner_type.value])

    def convert_from_counts(self, counts: int) -> float:
        """모터 카운트를 실제 단위로 변환"""
        if self.positioner_type == PositionerType.ANTENNA_HEIGHT:
            return counts / self.constants.HEIGHT_CONSTANTS['COUNTS_PER_MM']
        else:
            return counts / self.constants.STEPS_PER_DEGREE[self.positioner_type.value]

    def read_position(self) -> Optional[float]:
        """현재 위치 읽기 (변환된 단위)"""
        raw_counts = self.read_raw_location()
        if raw_counts is not None:
            return self.convert_from_counts(raw_counts)
        return None

    def set_target_position(self, target: float) -> bool:
        """목표 위치 설정"""
        try:
            # 값 범위 검증
            if self.positioner_type == PositionerType.ANTENNA_HEIGHT:
                if not (self.constants.HEIGHT_CONSTANTS['MIN_HEIGHT_MM'] <= target <= 
                       self.constants.HEIGHT_CONSTANTS['MAX_HEIGHT_MM']):
                    logging.error(f"높이 값 범위 초과: {target}mm")
                    return False
            elif not (0 <= target <= 360):
                logging.error(f"각도 값 범위 초과: {target}°")
                return False

            counts = self.convert_to_counts(target)
            self.instrument.write_long(2, counts, False, 3)
            return True
        except Exception as e:
            logging.error(f"목표 설정 오류: {e}")
            return False

    def start_movement(self) -> bool:
        """이동 시작"""
        try:
            self.instrument.write_bit(0, 1, 5)
            return True
        except Exception as e:
            logging.error(f"이동 시작 오류: {e}")
            return False

    def check_completion(self) -> bool:
        """이동 완료 상태 확인"""
        try:
            return bool(self.instrument.read_bit(self.reg_map['COMPLETE_BIT'], 2))
        except Exception as e:
            logging.error(f"완료 상태 확인 오류: {e}")
            return False

    def check_limits(self) -> bool:
        """리미트 스위치 상태 확인"""
        try:
            if self.positioner_type == PositionerType.ANTENNA_HEIGHT:
                upper = self.instrument.read_bit(self.reg_map['UPPER_LIMIT_BIT'], 2)
                lower = self.instrument.read_bit(self.reg_map['LOWER_LIMIT_BIT'], 2)
                return not (upper or lower)
            else:
                cw = self.instrument.read_bit(self.reg_map['CW_LIMIT_BIT'], 2)
                ccw = self.instrument.read_bit(self.reg_map['CCW_LIMIT_BIT'], 2)
                return not (cw or ccw)
        except Exception as e:
            logging.error(f"리미트 스위치 확인 오류: {e}")
            return False

    def move_up(self) -> bool:
        """높이 포지셔너 상승"""
        if self.positioner_type != PositionerType.ANTENNA_HEIGHT:
            return False
        try:
            return self.instrument.write_bit(self.reg_map['UP_BIT'], 1, 5)
        except Exception as e:
            logging.error(f"상승 명령 오류: {e}")
            return False

    def move_down(self) -> bool:
        """높이 포지셔너 하강"""
        if self.positioner_type != PositionerType.ANTENNA_HEIGHT:
            return False
        try:
            return self.instrument.write_bit(self.reg_map['DOWN_BIT'], 1, 5)
        except Exception as e:
            logging.error(f"하강 명령 오류: {e}")
            return False

    def stop_movement(self) -> bool:
        """긴급 정지"""
        try:
            return self.instrument.write_bit(self.reg_map['STOP_BIT'], 1, 5)
        except Exception as e:
            logging.error(f"정지 명령 오류: {e}")
            return False

    def move_to_position(self, target: float, wait_for_completion: bool = True) -> bool:
        """지정된 위치로 이동 (복합 동작)"""
        if not self.set_target_position(target):
            return False
            
        if not self.start_movement():
            return False
            
        if wait_for_completion:
            while not self.check_completion():
                time.sleep(0.1)
                if not self.check_limits():
                    self.stop_movement()
                    return False
                    
        return True

class MeasurementSystem:
    def __init__(self, ports: Dict[str, str]):
        """
        ports: 포트 매핑 딕셔너리
        예: {
            'ANT_ROLL': '/dev/ttyUSB0',
            'ANT_HEIGHT': '/dev/ttyUSB1',
            'EUT_ROLL': '/dev/ttyUSB2',
            'TT_ROLL': '/dev/ttyUSB3'
        }
        """
        self.antenna_roll = PositionerController(PositionerType.ANTENNA_ROLL, ports['ANT_ROLL'])
        self.antenna_height = PositionerController(PositionerType.ANTENNA_HEIGHT, ports['ANT_HEIGHT'])
        self.eut_roll = PositionerController(PositionerType.EUT_ROLL, ports['EUT_ROLL'])
        self.turntable_roll = PositionerController(PositionerType.TURNTABLE_ROLL, ports['TT_ROLL'])
        
    def initialize_all(self) -> bool:
        """모든 포지셔너 초기화"""
        success = True
        success &= self.antenna_roll.setup_instrument()
        success &= self.antenna_height.setup_instrument()
        success &= self.eut_roll.setup_instrument()
        success &= self.turntable_roll.setup_instrument()
        return success
        
    def move_to_measurement_position(self, 
                                   ant_roll_deg: float,
                                   ant_height_mm: float,
                                   eut_roll_deg: float,
                                   tt_roll_deg: float,
                                   wait_for_completion: bool = True) -> bool:
        """측정 위치로 모든 포지셔너 이동"""
        try:
            # 순차적 이동 실행
            moves = [
                (self.antenna_height, ant_height_mm),  # 높이 먼저 조정
                (self.antenna_roll, ant_roll_deg),
                (self.eut_roll, eut_roll_deg),
                (self.turntable_roll, tt_roll_deg)
            ]
            
            for controller, target in moves:
                if not controller.move_to_position(target, wait_for_completion):
                    logging.error(f"{controller.positioner_type.value} 이동 실패")
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"측정 위치 이동 오류: {e}")
            return False
            
    def get_all_positions(self) -> Dict[str, float]:
        """모든 포지셔너의 현재 위치 반환"""
        return {
            'antenna_roll': self.antenna_roll.read_position(),
            'antenna_height': self.antenna_height.read_position(),
            'eut_roll': self.eut_roll.read_position(),
            'turntable_roll': self.turntable_roll.read_position()
        }

    def emergency_stop_all(self) -> None:
        """모든 포지셔너 긴급 정지"""
        self.antenna_roll.stop_movement()
        self.antenna_height.stop_movement()
        self.eut_roll.stop_movement()
        self.turntable_roll.stop_movement()

# 사용 예시
if __name__ == "__main__":
    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 포트 설정
    ports = {
        'ANT_ROLL': 'COM5',
        'ANT_HEIGHT': 'COM6',
        'EUT_ROLL': 'COM7',
        'TT_ROLL': 'COM8'
    }
    
    # 시스템 초기화
    system = MeasurementSystem(ports)
    if not system.initialize_all():
        logging.error("시스템 초기화 실패")
        exit(1)
        
    # 초기 위치 확인
    positions = system.get_all_positions()
    logging.info(f"초기 위치: {positions}")
    
    # 예시: 측정 위치로 이동
    success = system.move_to_measurement_position(
        ant_roll_deg=45.0,    # 안테나 45도 회전
        ant_height_mm=1500.0, # 안테나 높이 1500mm
        eut_roll_deg=90.0,    # EUT 90도 회전
        tt_roll_deg=180.0     # 턴테이블 180도 회전
    )
    
    if success:
        logging.info("측정 위치 이동 완료")
        final_positions = system.get_all_positions()
        logging.info(f"최종 위치: {final_positions}")
    else:
        logging.error("측정 위치 이동 실패")