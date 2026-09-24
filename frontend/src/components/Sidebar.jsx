// Class names match styles/layout.css (.sidebar-brand, .sidebar-role,
// .sidebar-nav, .sidebar-footer .user-name).
export default function Sidebar({ items, active, onSelect, userName, roleLabel, onLogout, badges = {} }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">MediPass</div>
      <div className="sidebar-role">{roleLabel}</div>
      <nav className="sidebar-nav">
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
