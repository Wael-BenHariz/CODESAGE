import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ToastService } from '../../../../../core/services/toast.service';
import {
  MOCK_ORG_USAGE,
  MOCK_QUOTA_BARS,
  MOCK_USAGE_TOTALS,
  MockOrgQuota,
  cloneMockQuotas
} from '../../mock/usage-data';

/**
 * Platform Administration → Quotas & Utilisation (static PFE prototype) —
 * `/platform-admin/quotas`.
 *
 * Usage figures are fixed mock data; the quota editor mutates a local copy
 * of `MOCK_ORG_QUOTAS` in memory (visible in the "Quotas par organisation"
 * table) and confirms with a toast. Nothing is persisted server-side.
 */
@Component({
  selector: 'app-platform-quotas',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './platform-quotas.component.html'
})
export class PlatformQuotasComponent {
  private readonly toast = inject(ToastService);

  readonly totals = MOCK_USAGE_TOTALS;
  readonly quotaBars = MOCK_QUOTA_BARS;
  readonly orgUsage = MOCK_ORG_USAGE;

  /** Mutable local quota copy — the modal edits this signal only. */
  readonly quotas = signal<MockOrgQuota[]>(cloneMockQuotas());

  readonly modalOpen = signal(false);
  readonly orgDraft = signal('');
  readonly reviewQuotaDraft = signal(0);
  readonly llmQuotaDraft = signal(0);
  readonly storageQuotaDraft = signal('');

  readonly orgNames = computed(() => this.quotas().map(quota => quota.organization));

  /** Progress-bar tone: green < 70 %, orange < 90 %, red beyond. */
  barTone(percent: number): string {
    if (percent >= 90) return 'critical';
    if (percent >= 70) return 'warning';
    return '';
  }

  openQuotaModal(): void {
    const first = this.quotas()[0];
    if (!first) {
      return;
    }
    this.orgDraft.set(first.organization);
    this.applyOrgDraft(first);
    this.modalOpen.set(true);
  }

  closeQuotaModal(): void {
    this.modalOpen.set(false);
  }

  /** Reload the draft inputs when the selected organization changes. */
  setOrgDraft(organization: string): void {
    this.orgDraft.set(organization);
    const quota = this.quotas().find(item => item.organization === organization);
    if (quota) {
      this.applyOrgDraft(quota);
    }
  }

  onOverlayClick(event: Event): void {
    if (event.target === event.currentTarget) {
      this.closeQuotaModal();
    }
  }

  saveQuotas(): void {
    const organization = this.orgDraft();
    if (!organization) {
      return;
    }
    this.quotas.update(list =>
      list.map(quota =>
        quota.organization === organization
          ? {
              ...quota,
              reviewQuota: this.toNumber(this.reviewQuotaDraft()),
              llmQuota: this.toNumber(this.llmQuotaDraft()),
              storageQuota: this.storageQuotaDraft().trim() || quota.storageQuota
            }
          : quota
      )
    );
    this.closeQuotaModal();
    this.toast.success('Les quotas ont été mis à jour.');
  }

  private applyOrgDraft(quota: MockOrgQuota): void {
    this.reviewQuotaDraft.set(quota.reviewQuota);
    this.llmQuotaDraft.set(quota.llmQuota);
    this.storageQuotaDraft.set(quota.storageQuota);
  }

  private toNumber(raw: number): number {
    const value = Number(raw);
    return Number.isFinite(value) && value >= 0 ? Math.round(value) : 0;
  }
}
