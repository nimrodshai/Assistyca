type AnalyticsPayload = Record<string, string | number | boolean | undefined>;

const development = import.meta.env.DEV;

export function trackEvent(eventName: string, payload: AnalyticsPayload = {}) {
  if (development) {
    console.info(`[analytics] ${eventName}`, payload);
  }
}
