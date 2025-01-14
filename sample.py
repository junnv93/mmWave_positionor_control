# simple_modbus_cli.py
import minimalmodbus
import serial
import sys

def main():
    # -----------------------------------------
    # 1. MinimalModbus 설정
    # -----------------------------------------
    port = 'COM15'           # 예시 시리얼 포트 이름
    slave_address = 1        # 예시 슬레이브 주소
    instrument = minimalmodbus.Instrument(port, slave_address)
    instrument.serial.baudrate = 19200
    instrument.serial.bytesize = 8
    instrument.serial.parity = serial.PARITY_NONE
    instrument.serial.stopbits = 1
    instrument.serial.timeout = 2
    
    # 옵션 (필요하다면 추가)
    instrument.serial.rts = False
    instrument.serial.dtr = False
    instrument.serial.xonxoff = False
    
    print(f"포트: {port}, 슬레이브 주소: {slave_address} 연결됨.")
    print("사용 예: read_bit(2, 2)")
    print("          read_long(0, 3, False, 3)")
    print("          write_bit(5, 1, 5)")
    print("          write_long(10, 12345, 3, False)")
    print("종료를 원하면 'exit' 또는 'quit' 입력 후 Enter")

    while True:
        # -----------------------------------------
        # 2. 사용자 명령어 입력
        # -----------------------------------------
        command_str = input("\n명령어를 입력하세요: ").strip()
        
        if command_str.lower() in ("exit", "quit"):
            print("프로그램을 종료합니다.")
            break
        
        # -----------------------------------------
        # 3. 명령어 파싱
        # -----------------------------------------
        # 예: read_bit(2,2) -> 함수명: read_bit, 인자: [2, 2]
        #     write_long(10, 12345, 3, False) -> 함수명: write_long, 인자: [10, 12345, 3, False]
        # 문자열 형태에서 ( ) 안의 인자를 추출하고, 쉼표로 구분해 처리.
        try:
            func_name, arg_str = command_str.split("(", 1)
            func_name = func_name.strip()
            arg_str = arg_str.strip(")")
            if arg_str.strip() == "":
                args = []
            else:
                # 쉼표로 분할
                raw_args = [x.strip() for x in arg_str.split(",")]
                # 각 인자를 숫자나 bool, str 등으로 변환
                args = []
                for item in raw_args:
                    # True/False 변환
                    if item.lower() == 'true':
                        args.append(True)
                    elif item.lower() == 'false':
                        args.append(False)
                    # 정수 변환
                    elif item.isdigit() or (item.startswith('-') and item[1:].isdigit()):
                        args.append(int(item))
                    else:
                        # 소수점 포함 여부
                        try:
                            float_val = float(item)
                            args.append(float_val)
                        except ValueError:
                            # 문자열 그대로
                            args.append(item)
            
            # -----------------------------------------
            # 4. 함수 호출 로직
            # -----------------------------------------
            # func_name에 따라 instrument의 메서드를 호출
            # 안전을 위해 getattr 사용
            if hasattr(instrument, func_name):
                func = getattr(instrument, func_name)
                result = func(*args)
                print(f"\n[결과] {func_name}{tuple(args)} -> {result}")
            else:
                print(f"알 수 없는 함수명입니다: {func_name}")
        
        except Exception as e:
            print(f"명령 처리 중 오류가 발생했습니다: {e}")

    # -----------------------------------------
    # 5. 종료 처리
    # -----------------------------------------
    try:
        instrument.serial.close()
    except:
        pass

if __name__ == "__main__":
    main()
