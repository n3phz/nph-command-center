export interface ServiceStatus {
  service: string;
  status: string;
  version?: string;
  error?: string;
}

export const ServiceStatusBadge: React.FC<{ status: string; serviceName?: string }> = ({ status, serviceName }) => {
  const dotClass = status === 'healthy' ? 'healthy' : status === 'degraded' ? 'degraded' : 'down';
  
  return (
    <div className="service-status">
      <span className={`dot ${dotClass}`} />
      <span>{serviceName || status}</span>
    </div>
  );
};

export default ServiceStatusBadge;