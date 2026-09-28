// Keep backend/quality policy independent of the reader UI.
export function isIOS(device = navigator) {
  return /iphone|ipad|ipod/i.test(device.userAgent || '')
    || (device.platform === 'MacIntel' && device.maxTouchPoints > 1);
}

export function qualitySteps(value) {
  return Number(value) === 8 ? 8 : 4;
}

export function backendOrder(want, hasWebGpu, device = navigator) {
  if (isIOS(device)) return ['wasm'];
  return want === 'auto' ? (hasWebGpu ? ['webgpu', 'wasm'] : ['wasm']) : [want];
}

// ORT proxy transfers (detaches) input buffers. Styles and intermediate tensors
// are reused by Supertonic, so only disposable copies may cross the worker boundary.
export function copyingInputs(session, Tensor) {
  return { run: (feeds, ...rest) => session.run(Object.fromEntries(
    Object.entries(feeds).map(([key, value]) => [key, new Tensor(value.type, value.data.slice(), value.dims)])
  ), ...rest) };
}
