class VideoUdpStreamer:
    def __init__(self, host="127.0.0.1", port=5006, bitrate=4_000_000):
        self.host = host
        self.port = port
        self.bitrate = bitrate
        self.encoder = None
        self.output = None

    def start(self, picam2, stream_name="main"):
        from picamera2.encoders import H264Encoder
        from picamera2.outputs import FfmpegOutput

        self.encoder = H264Encoder(bitrate=self.bitrate)
        self.output = FfmpegOutput(f"-f mpegts udp://{self.host}:{self.port}")
        picam2.start_encoder(self.encoder, self.output, name=stream_name)

    def stop(self, picam2):
        if self.encoder is not None:
            picam2.stop_encoder(self.encoder)
            self.encoder = None
            self.output = None
