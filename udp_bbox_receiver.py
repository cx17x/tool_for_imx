import argparse
import socket


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", help="UDP host to bind")
    parser.add_argument("--port", type=int, default=5005, help="UDP port to bind")
    parser.add_argument("--buffer-size", type=int, default=65535, help="Receive buffer size")
    return parser.parse_args()


def main():
    args = get_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    print(f"Listening for bbox UDP on {args.host}:{args.port}")

    while True:
        data, address = sock.recvfrom(args.buffer_size)
        print(f"{address}: {data.decode('utf-8', errors='replace')}")


if __name__ == "__main__":
    main()
