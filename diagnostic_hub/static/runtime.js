'use strict';
// Ingress can be opened through plain HTTP on a LAN. randomUUID() is
// secure-context-only; getRandomValues() remains available there.
window.diagnosticRuntime = Object.freeze({
  requestId() {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  },
  requestScope(parent, milliseconds = 25000) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (parent?.aborted) abort();
    else parent?.addEventListener('abort', abort, {once:true});
    const timeout = setTimeout(abort, milliseconds);
    return {signal:controller.signal, close(){ clearTimeout(timeout);parent?.removeEventListener('abort',abort); }};
  }
});
