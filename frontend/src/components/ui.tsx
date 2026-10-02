// Button component with hover/active/disabled states

interface ButtonProps {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'secondary' | 'danger' | 'success' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  className?: string;
}

export function Button({ children, onClick, variant = 'primary', size = 'md', disabled = false, className = '' }: ButtonProps) {
  return (
    <button
      className={`btn btn-${variant} btn-${size} ${disabled ? 'btn-disabled' : ''} ${className}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

// HP Bar component
interface HPBarProps {
  current: number;
  maximum: number;
  showLabel?: boolean;
}

export function HPBar({ current, maximum, showLabel = true }: HPBarProps) {
  const pct = Math.max(0, Math.min(100, (current / maximum) * 100));
  const color = pct > 60 ? '#00d4ff' : pct > 30 ? '#ffaa00' : '#ff4444';
  
  return (
    <div className="hp-bar-container">
      {showLabel && (
        <div className="hp-bar-label">
          <span className="hp-current">{current}</span>
          <span className="hp-sep">/</span>
          <span className="hp-max">{maximum}</span>
        </div>
      )}
      <div className="hp-bar">
        <div className="hp-bar-fill" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      {pct <= 25 && <div className="hp-bar-warning">⚠ LOW HP</div>}
    </div>
  );
}

// Damage number floating effect
interface DamageNumberProps {
  value: number;
  isCrit: boolean;
  isHeal: boolean;
}

export function DamageNumber({ value, isCrit, isHeal }: DamageNumberProps) {
  return (
    <div className={`damage-number ${isCrit ? 'crit' : ''} ${isHeal ? 'heal' : ''}`}>
      {isHeal ? '+' : ''}{value}
    </div>
  );
}

// Card component
interface CardProps {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
}

export function Card({ children, className = '', onClick }: CardProps) {
  return (
    <div className={`card ${onClick ? 'card-clickable' : ''} ${className}`} onClick={onClick}>
      {children}
    </div>
  );
}