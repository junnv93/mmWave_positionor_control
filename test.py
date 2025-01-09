import time
import logging
from modbus_control import PositionerType, PositionerController

# 로깅 설정
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def test_antenna_roll(port='COM15', target_position=90.0):
    try:
        # 안테나 롤 포지셔너 초기화
        ant_roll = PositionerController(
            positioner_type=PositionerType.ANTENNA_ROLL,
            port_info=port
        )

        # 현재 위치 읽기
        current_pos = ant_roll.read_position()
        print(f"\n현재 안테나 롤 위치: {current_pos:.2f}°")

        # 목표 위치 설정
        print(f"\n목표 위치 {target_position}°로 설정 중...")
        if not ant_roll.set_target_position(target_position):
            print("목표 위치 설정 실패")
            return False

        # 이동 시작
        print("이동 시작...")
        if not ant_roll.start_movement():
            print("이동 시작 실패")
            return False

        # 이동하는 동안 현재 위치 모니터링
        print("\n현재 위치 모니터링 중...")
        start_time = time.time()
        while True:
            current_pos = ant_roll.read_position()
            print(f"현재 위치: {current_pos:.2f}°")
            
            # 이동 완료 확인
            if ant_roll.is_movement_complete(target_position):
                print("\n이동 완료!")
                break
                
            # 30초 타임아웃
            if time.time() - start_time > 30:
                print("\n타임아웃: 30초 초과")
                break
                
            time.sleep(0.5)  # 0.5초마다 위치 확인

        # 최종 위치 확인
        final_pos = ant_roll.read_position()
        print(f"\n최종 위치: {final_pos:.2f}°")

        return True

    except Exception as e:
        print(f"오류 발생: {e}")
        return False

if __name__ == "__main__":
    # 테스트 실행
    target = float(input("목표 위치를 입력하세요 (0-180도): "))
    test_antenna_roll(target_position=target)