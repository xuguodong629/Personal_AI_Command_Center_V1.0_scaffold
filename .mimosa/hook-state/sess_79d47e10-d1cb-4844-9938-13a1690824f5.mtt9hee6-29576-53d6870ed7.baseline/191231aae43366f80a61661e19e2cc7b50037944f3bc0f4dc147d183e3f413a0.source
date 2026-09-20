import { useEffect, useState } from 'react';

/** 任务运行期间每秒跳动的已用秒数，结束时归零 */
export function useElapsed(running: boolean): number {
  const [s, setS] = useState(0);
  useEffect(() => {
    if (!running) return;
    setS(0);
    const t = setInterval(() => setS(v => v + 1), 1000);
    return () => clearInterval(t);
  }, [running]);
  return s;
}
