import socket

UDP_IP = "0.0.0.0"   # слушать все интерфейсы
UDP_PORT = 5005      # нужный UDP порт

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

print(f"Listening UDP {UDP_IP}:{UDP_PORT}")

while True:
    data, addr = sock.recvfrom(4096)  # размер буфера

    print(f"\nReceived from {addr}")
    print(f"Raw bytes: {data}")

    try:
        text = data.decode("utf-8")
        print(f"Decoded: {text}")
    except UnicodeDecodeError:
        print("Cannot decode as UTF-8")