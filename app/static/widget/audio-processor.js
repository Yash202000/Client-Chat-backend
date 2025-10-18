
class SilenceDetector extends AudioWorkletProcessor {
    constructor(options) {
        super();
        this.silenceDelay = options.processorOptions.silenceDelay || 1000;
        this.threshold = options.processorOptions.threshold || 0.01;
        this.lastSignalTime = currentTime;
        this.speaking = false;

        this.port.onmessage = (event) => {
            if (event.data.silenceDelay) {
                this.silenceDelay = event.data.silenceDelay;
            }
            if (event.data.threshold) {
                this.threshold = event.data.threshold;
            }
        };
    }

    process(inputs) {
        const input = inputs[0];
        if (input.length > 0) {
            const samples = input[0];
            let sum = 0;
            for (let i = 0; i < samples.length; ++i) {
                sum += Math.abs(samples[i]);
            }
            const rms = sum / samples.length;

            if (rms > this.threshold) {
                this.lastSignalTime = currentTime;
                if (!this.speaking) {
                    this.speaking = true;
                    this.port.postMessage('speechStart');
                }
            } else {
                if (this.speaking && (currentTime - this.lastSignalTime) * 1000 > this.silenceDelay) {
                    this.speaking = false;
                    this.port.postMessage('speechEnd');
                }
            }
        }
        return true;
    }
}

registerProcessor('silence-detector', SilenceDetector);
