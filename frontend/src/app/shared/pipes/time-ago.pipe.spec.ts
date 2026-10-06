import { TimeAgoPipe } from './time-ago.pipe';

describe('TimeAgoPipe', () => {
  const pipe = new TimeAgoPipe();
  const now = Date.now();
  const ago = (ms: number) => new Date(now - ms).toISOString();

  it('formats minutes, hours, days, months and years', () => {
    expect(pipe.transform(ago(5 * 60_000))).toBe('5m ago');
    expect(pipe.transform(ago(3 * 3_600_000))).toBe('3h ago');
    expect(pipe.transform(ago(2 * 86_400_000))).toBe('2d ago');
    expect(pipe.transform(ago(90 * 86_400_000))).toBe('3mo ago');
    expect(pipe.transform(ago(400 * 86_400_000))).toBe('1y ago');
  });

  it('says "just now" inside the first minute (incl. future timestamps)', () => {
    expect(pipe.transform(ago(10_000))).toBe('just now');
    expect(pipe.transform(new Date(now + 60_000).toISOString())).toBe('just now');
  });

  it('returns an empty string for missing or unparseable input', () => {
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
    expect(pipe.transform('not-a-date')).toBe('');
  });
});
