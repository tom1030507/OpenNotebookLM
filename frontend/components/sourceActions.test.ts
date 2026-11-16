import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api';

import { uploadFilesInTurn } from './sourceActions';

const files = (...names: string[]) => names.map((name) => new File(['x'], name));
const busy = (retryAfter?: number) => new ApiError(429, 'Too many concurrent operations', retryAfter);

describe('uploadFilesInTurn', () => {
  it('waits out a busy slot and goes on with the rest of the batch', async () => {
    const [a, b, c, d] = files('a.pdf', 'b.pdf', 'c.pdf', 'd.pdf');
    const upload = vi.fn()
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(busy(1))
      .mockResolvedValue(undefined);
    const wait = vi.fn(async () => undefined);

    const outcome = await uploadFilesInTurn([a, b, c, d], upload, wait);

    expect(outcome.failed).toEqual([]);
    expect(upload.mock.calls.map(([file]) => file.name))
      .toEqual(['a.pdf', 'b.pdf', 'c.pdf', 'c.pdf', 'd.pdf']);
    expect(wait).toHaveBeenCalledWith(1000);
  });

  it('backs off when the server keeps asking for one second', async () => {
    const upload = vi.fn()
      .mockRejectedValueOnce(busy(1))
      .mockRejectedValueOnce(busy(1))
      .mockRejectedValueOnce(busy(1))
      .mockResolvedValue(undefined);
    const wait = vi.fn<(ms: number) => Promise<void>>(async () => undefined);

    await uploadFilesInTurn(files('a.pdf'), upload, wait);

    expect(wait.mock.calls.map(([ms]) => ms)).toEqual([1000, 2000, 4000]);
  });

  it('reports a file that fails for another reason and still tries the next', async () => {
    const [a, b] = files('a.pdf', 'b.pdf');
    const upload = vi.fn()
      .mockRejectedValueOnce(new ApiError(400, 'File type is not supported'))
      .mockResolvedValue(undefined);
    const wait = vi.fn(async () => undefined);

    const outcome = await uploadFilesInTurn([a, b], upload, wait);

    expect(outcome.failed).toEqual([{ file: a, message: 'File type is not supported' }]);
    expect(upload).toHaveBeenCalledTimes(2);
    expect(wait).not.toHaveBeenCalled();
  });

  it('gives up on a file once it has waited three minutes', async () => {
    const [a] = files('a.pdf');
    const upload = vi.fn().mockRejectedValue(new ApiError(429, 'Too many requests', 60));
    const wait = vi.fn(async () => undefined);

    const outcome = await uploadFilesInTurn([a], upload, wait);

    expect(wait).toHaveBeenCalledTimes(3);
    expect(outcome.failed).toEqual([{ file: a, message: 'Too many requests' }]);
  });
});
