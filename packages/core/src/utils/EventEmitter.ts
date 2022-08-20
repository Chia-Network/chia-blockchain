type Callback = (...args: any[]) => void;

export default class EventEmitter {
  private events: {
    [key: string]: Callback[];
  } = {};

  on(event: string, listener: Callback) {
    if (!(event in this.events)) {
      this.events[event] = [];
    }
    this.events[event].push(listener);

    return () => this.remove(event, listener);
  }

  remove(event: string, listener: Callback) {
    if (!(event in this.events)) {
      return;
    }

    if (!this.events[event].includes(listener)) {
      return;
    }

    this.events[event] = this.events[event].filter((l) => l !== listener);
  }

  emit(event: string, ...args: any[]) {
    if (!(event in this.events)) {
      return;
    }
    this.events[event].forEach((listener) => listener(...args));
  }

  once(event: string, listener: Callback) {
    const remove = this.on(event, (...args) => {
      remove();
      listener(...args);
    });
  }
}
