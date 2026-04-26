// Tiny pub-sub so only one audio plays at a time.
type Listener = (currentSrc: string | null) => void;
type CommandListener = (cmd: { type: "play" | "stop"; src: string }) => void;
type DemoEventListener = (event: "started" | "reset") => void;

const listeners = new Set<Listener>();
const commandListeners = new Set<CommandListener>();
const demoListeners = new Set<DemoEventListener>();
let current: string | null = null;

export const audioBus = {
  setCurrent(src: string | null) {
    current = src;
    listeners.forEach((l) => l(current));
  },
  subscribe(l: Listener) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  command(cmd: { type: "play" | "stop"; src: string }) {
    commandListeners.forEach((l) => l(cmd));
  },
  subscribeCommand(l: CommandListener) {
    commandListeners.add(l);
    return () => commandListeners.delete(l);
  },
  emitDemo(event: "started" | "reset") {
    demoListeners.forEach((l) => l(event));
  },
  subscribeDemo(l: DemoEventListener) {
    demoListeners.add(l);
    return () => demoListeners.delete(l);
  },
  get current() {
    return current;
  },
};
