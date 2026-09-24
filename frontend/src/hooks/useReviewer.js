import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';

const REFRESH_MS = 60_000;

/**
 * Is the logged-in user a MediPass reviewer (MEDIPASS_REVIEWER_EMAILS on the
 * server), and how many doctors are waiting? Non-reviewers get
 * { isReviewer: false } and nothing else is fetched.
 */
export default function useReviewer() {
  const [isReviewer, setIsReviewer] = useState(false);
  const [pending, setPending] = useState(0);

  const refresh = useCallback(() => api.reviewerListDoctors('pending')
    .then((d) => setPending(d.counts.pending))
    .catch(() => {}), []);

  useEffect(() => {
    let timer;
    api.getReviewerStatus()
      .then(({ is_reviewer: yes }) => {
        setIsReviewer(yes);
        if (yes) {
          refresh();
          timer = setInterval(refresh, REFRESH_MS);
        }
      })
      .catch(() => setIsReviewer(false));
    return () => clearInterval(timer);
  }, [refresh]);

  return { isReviewer, pending, refresh };
}
