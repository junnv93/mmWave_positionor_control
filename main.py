# main.py
import logging
import sys
from modbus_control import ModbusDevice
from data_acquisition import measure_eirp
from bayesian_optimization import SimpleBayesianOptimizer

def main():
    # 로깅 설정
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        stream=sys.stdout)

    # (1) 포지셔너 초기화
    # 실제 변환 계수 값은 장비 스펙에 맞춰서 수정
    conversion_factors = {
        "height": 8960,  # 1mm당 8960 counts
        "roll": 1000     # 1도당 1000 counts
    }

    device_ht = ModbusDevice(
        name="Height Positioner",
        port="COM3",
        address=1,
        conversion_factors=conversion_factors,
        has_height=True
    )
    device_ht.setup_instrument()

    device_roll = ModbusDevice(
        name="Roll Positioner",
        port="COM4",
        address=2,
        conversion_factors=conversion_factors,
        has_height=False
    )
    device_roll.setup_instrument()

    # (2) 스펙트럼 분석기 기본 설정
    analyzer_settings = {
        'Transducer': 'MyTransducer', 
        'Offset Level': 0,
        'Reference Level': 'AUTO',   # 자동 기준 레벨
        'Attenuation': 'AUTO',       # 자동 감쇠
        'Span': 100e6,               # 스팬 100 MHz
        'Preamp': 'OFF',
        'RBW': 1e6,
        'VBW': 3e6,
        'Trace Mode': 'WRIT',
        'Average Type': 'POIN',
        'Det Type': 'MAXH',
        'Channel Bandwidth': 20e6,
        'Sweep Time': 'AUTO',
        'Sweep Points': 1001,
        'Sweep Counts': 5,
        'Wait Time': 1
    }

    # (3) 베이지안(임시 랜덤) 옵티마이저 생성
    optimizer = SimpleBayesianOptimizer()

    excel_file_path = r"C:\Path\To\Your\ExcelFile.xlsx"
    center_frequency = 28e9  # 28 GHz

    # (4) 초기 샘플링
    init_samples = 3
    for _ in range(init_samples):
        # 예시: 초기 위치를 고정값으로 사용
        init_height = 170
        init_roll = 0
        init_theta = 0
        power = measure_eirp(device_ht, device_roll,
                             analyzer_settings, excel_file_path,
                             init_height, init_roll, center_frequency)
        optimizer.add_observation((init_theta, init_roll, init_height), power)
        logging.info(f"[INIT] Power = {power} dBm")

    # (5) 최적화 루프
    max_iterations = 5
    for i in range(max_iterations):
        next_theta, next_roll, next_height = optimizer.suggest_next_point()
        # 여기서는 theta를 따로 안 쓰고, roll/height만 적용하는 예시
        power = measure_eirp(device_ht, device_roll,
                             analyzer_settings, excel_file_path,
                             next_height, next_roll, center_frequency)
        optimizer.add_observation((next_theta, next_roll, next_height), power)
        logging.info(f"[ITER {i}] H={next_height}mm, R={next_roll}deg, Power={power} dBm")

    logging.info("Optimization finished.")

if __name__ == "__main__":
    main()
