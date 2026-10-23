'use strict';
// A thread keeps synchronous SDK calls inside the supervised script process.
const {Worker, isMainThread, workerData} = require('node:worker_threads');
const LIMIT = 1048576;

if (!isMainThread && workerData?.localEEBridge === true) {
  const state = new Int32Array(workerData.control);
  const output = new Uint8Array(workerData.output);
  function finish(message) {
    let bytes = Buffer.from(JSON.stringify(message));
    if (bytes.length > output.length) {
      bytes = Buffer.from(JSON.stringify({ok: false, error: 'Local GEE bridge response exceeds 1 MiB'}));
    }
    output.set(bytes);
    Atomics.store(state, 1, bytes.length);
    Atomics.store(state, 0, 1);
    Atomics.notify(state, 0);
  }
  Promise.resolve().then(() => require('./transport.cjs').request(workerData.payload))
    .then(value => finish({ok: true, value}))
    .catch(error => finish({ok: false, error: error.message}));
} else {
  module.exports.send = function send(payload) {
    if (Buffer.byteLength(JSON.stringify(payload)) > LIMIT) throw Error('Local GEE bridge request exceeds 1 MiB');
    const control = new SharedArrayBuffer(8);
    const output = new SharedArrayBuffer(LIMIT);
    const state = new Int32Array(control);
    const worker = new Worker(__filename, {workerData: {localEEBridge: true, payload, control, output}});
    worker.on('error', () => {}); // Startup/fatal errors are bounded by the wait below.
    worker.unref();
    try {
      if (Atomics.wait(state, 0, 0, 110000) === 'timed-out') throw Error('Local GEE bridge timed out');
      const message = JSON.parse(Buffer.from(output, 0, Atomics.load(state, 1)).toString('utf8'));
      if (!message.ok) throw Error(message.error);
      return message.value;
    } finally {
      void worker.terminate();
    }
  };
}
