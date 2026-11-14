output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}

output "rds_primary_endpoint" {
  description = "Endpoint of the primary RDS instance"
  value       = aws_db_instance.primary.endpoint
}

output "rds_primary_identifier" {
  description = "Identifier of the primary RDS instance"
  value       = aws_db_instance.primary.identifier
}

output "rds_replica_endpoint" {
  description = "Endpoint of the read replica"
  value       = aws_db_instance.replica.endpoint
}

output "rds_replica_identifier" {
  description = "Identifier of the read replica"
  value       = aws_db_instance.replica.identifier
}

output "app_security_group_id" {
  description = "Security group ID for the application"
  value       = aws_security_group.app.id
}

output "rds_security_group_id" {
  description = "Security group ID for the RDS instances"
  value       = aws_security_group.rds.id
}
