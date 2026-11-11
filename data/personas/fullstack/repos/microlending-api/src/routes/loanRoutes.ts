import { Router, Request, Response } from 'express';
import { getRepository } from 'typeorm';
import { Loan } from '../entity/Loan';
import { User } from '../entity/User';
import { getCreditScore } from '../services/creditService';
import { createPayout } from '../services/paymentService';

const router = Router();

// Submit a new loan application
router.post('/', async (req: Request, res: Response) => {
  const { userId, amount, termMonths } = req.body;
  const userRepo = getRepository(User);
  const loanRepo = getRepository(Loan);
  const user = await userRepo.findOneOrFail(userId);

  // Simple credit‑score rule: must be >= 600
  const creditScore = await getCreditScore(user.id);
  if (creditScore < 600) {
    return res.status(400).json({ error: 'Credit score too low' });
  }

  const loan = loanRepo.create({ borrower: user, amount, termMonths, status: 'approved' });
  await loanRepo.save(loan);
  res.status(201).json(loan);
});

// Trigger payout after approval
router.post('/:id/payout', async (req: Request, res: Response) => {
  const loanRepo = getRepository(Loan);
  const loan = await loanRepo.findOneOrFail(req.params.id, { relations: ['borrower'] });
  if (loan.status !== 'approved') {
    return res.status(400).json({ error: 'Loan not approved' });
  }
  const payout = await createPayout(loan);
  loan.status = 'disbursed';
  await loanRepo.save(loan);
  res.json({ payoutId: payout.id, status: loan.status });
});

export default router;
