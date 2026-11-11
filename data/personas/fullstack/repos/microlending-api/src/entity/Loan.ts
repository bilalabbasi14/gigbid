import { Entity, PrimaryGeneratedColumn, Column, ManyToOne, CreateDateColumn, UpdateDateColumn } from 'typeorm';
import { User } from './User';

@Entity('loans')
export class Loan {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @ManyToOne(() => User, user => user.loans)
  borrower!: User;

  @Column('decimal', { precision: 10, scale: 2 })
  amount!: number;

  @Column('int')
  termMonths!: number;

  @Column('varchar')
  status: 'pending' | 'approved' | 'disbursed' | 'repaid' = 'pending';

  @CreateDateColumn()
  createdAt!: Date;

  @UpdateDateColumn()
  updatedAt!: Date;
}
