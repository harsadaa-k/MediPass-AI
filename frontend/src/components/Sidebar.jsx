import { useEffect, useRef } from 'react';

// Class names match styles/layout.css (.sidebar-brand, .sidebar-role,
// .sidebar-nav, .sidebar-footer .user-name).
export default function Sidebar({ items, active, onSelect, userName, roleLabel, onLogout, badges = {} }) {
  const navRef = useRef(null);

  // Phones show the menu as one swipeable row: keep the current page's
  // button in view (no effect on the desktop column, which doesn't scroll sideways).
  useEffect(() => {
    // on a phone the menu sits above the page: start each new page at its top
    // (also when a page is opened from a button, e.g. "View patient")
    if (window.matchMedia?.('(max-width: 720px)').matches) window.scrollTo({ top: 0 });
    const nav = navRef.current;
    const btn = nav?.querySelector('button.active');
    if (!nav || !btn || nav.scrollWidth <= nav.clientWidth) return;
    nav.scrollTo({ left: btn.offsetLeft - (nav.clientWidth - btn.offsetWidth) / 2, behavior: 'smooth' });
  }, [active]);

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">MediPass</div>
      <div className="sidebar-role">{roleLabel}</div>
      <nav className="sidebar-nav" ref={navRef}>
        {items.map((item) => {
          const badgeCount = badges[item.key] || 0;
          return (
            <button
              key={item.key}
              className={active === item.key ? 'active' : ''}
              onClick={() => onSelect(item.key)}
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
            >
              <span>{item.label}</span>
              {badgeCount > 0 && (
                <span style={{
                  backgroundColor: '#dc2626',
                  color: 'white',
                  borderRadius: '12px',
                  padding: '2px 8px',
                  fontSize: '0.75rem',
                  fontWeight: 'bold'
                }}>
                  {badgeCount}
                </span>
              )}
            </button>
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <div className="user-name">{userName}</div>
        <button className="sidebar-signout" onClick={onLogout}>
          Sign out
        </button>
      </div>
    </aside>
  );
}
