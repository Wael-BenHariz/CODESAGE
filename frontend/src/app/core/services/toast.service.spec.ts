import { TestBed, fakeAsync, tick } from '@angular/core/testing';

import { ToastService } from './toast.service';

describe('ToastService', () => {
  let service: ToastService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(ToastService);
  });

  it('pushes a toast and exposes it through the readonly signal', () => {
    service.success('Saved');

    expect(service.toasts().length).toBe(1);
    expect(service.toasts()[0].kind).toBe('success');
    expect(service.toasts()[0].message).toBe('Saved');
  });

  it('supports the three kinds via show/success/error/info', () => {
    service.show('info', 'a');
    service.error('b');
    service.info('c');

    expect(service.toasts().map(t => t.kind)).toEqual(['info', 'error', 'info']);
    expect(service.toasts().map(t => t.message)).toEqual(['a', 'b', 'c']);
  });

  it('auto-dismisses each kind after its TTL', fakeAsync(() => {
    service.success('fast');
    service.error('slow');

    tick(4000); // success TTL elapses
    expect(service.toasts().map(t => t.message)).toEqual(['slow']);

    tick(4000); // error TTL (8000 total)
    expect(service.toasts().length).toBe(0);
  }));

  it('dismisses by id without touching the others', () => {
    service.info('one');
    const second = service.info('two');
    service.info('three');

    service.dismiss(second);

    expect(service.toasts().map(t => t.message)).toEqual(['one', 'three']);
  });

  it('keeps dismissing after expiry harmlessly (idempotent)', fakeAsync(() => {
    const id = service.success('gone');
    tick(4000);
    expect(service.toasts().length).toBe(0);

    service.dismiss(id);
    expect(service.toasts().length).toBe(0);
  }));
});
