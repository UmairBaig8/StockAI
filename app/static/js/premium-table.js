class PremiumTable {
  constructor(container, options) {
    this.container = typeof container === 'string' ? document.getElementById(container) : container;
    this.columns = options.columns || [];
    this.data = options.data || [];
    this.pageSize = options.pageSize || 20;
    this.searchable = options.searchable !== false;
    this.sortable = options.sortable !== false;
    this.pagination = options.pagination !== false;
    this.emptyMessage = options.emptyMessage || 'No data available';
    this.loadingMessage = options.loadingMessage || 'Loading...';
    this.searchPlaceholder = options.searchPlaceholder || 'Search...';
    this.onRowClick = options.onRowClick || null;
    this.renderCell = options.renderCell || null;
    this.page = 0;
    this.sortCol = null;
    this.sortDir = 'asc';
    this.searchQuery = '';
    this.filteredData = [...this.data];
    this.render();
  }

  setData(data) {
    this.data = [...data];
    this.applyFilters();
    this.renderBody();
    this.renderPagination();
  }

  applyFilters() {
    let result = [...this.data];
    if (this.searchQuery) {
      const q = this.searchQuery.toLowerCase();
      result = result.filter(row =>
        this.columns.some(col => {
          const val = row[col.key];
          return val != null && String(val).toLowerCase().includes(q);
        })
      );
    }
    if (this.sortCol !== null) {
      const col = this.columns[this.sortCol];
      result.sort((a, b) => {
        let va = a[col.key], vb = b[col.key];
        if (va == null) va = '';
        if (vb == null) vb = '';
        const na = parseFloat(va), nb = parseFloat(vb);
        if (!isNaN(na) && !isNaN(nb)) {
          return this.sortDir === 'asc' ? na - nb : nb - na;
        }
        const sa = String(va).toLowerCase(), sb = String(vb).toLowerCase();
        if (sa < sb) return this.sortDir === 'asc' ? -1 : 1;
        if (sa > sb) return this.sortDir === 'asc' ? 1 : -1;
        return 0;
      });
    }
    this.filteredData = result;
    if (this.page * this.pageSize >= result.length) {
      this.page = Math.max(0, Math.ceil(result.length / this.pageSize) - 1);
    }
  }

  render() {
    this.container.innerHTML = '';
    this.container.className = 'premium-table-wrap';

    if (this.searchable) {
      const searchBar = document.createElement('div');
      searchBar.className = 'pt-search-bar';
      searchBar.innerHTML = `
        <div class="pt-search-icon">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        </div>
        <input type="text" class="pt-search-input" placeholder="${this.searchPlaceholder}" />
      `;
      this.container.appendChild(searchBar);
      this.searchInput = searchBar.querySelector('.pt-search-input');
      this.searchInput.addEventListener('input', (e) => {
        this.searchQuery = e.target.value;
        this.page = 0;
        this.applyFilters();
        this.renderBody();
        this.renderPagination();
      });
    }

    const tableWrap = document.createElement('div');
    tableWrap.className = 'pt-table-scroll';

    const table = document.createElement('table');
    table.className = 'pt-table';

    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    this.columns.forEach((col, i) => {
      const th = document.createElement('th');
      th.className = 'pt-th' + (col.className ? ' ' + col.className : '');
      th.innerHTML = `<span class="pt-th-label">${col.label}</span>`;
      if (this.sortable && col.sortable !== false) {
        th.classList.add('pt-sortable');
        th.addEventListener('click', () => this.handleSort(i));
      }
      if (col.width) th.style.width = col.width;
      if (col.minWidth) th.style.minWidth = col.minWidth;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    tbody.className = 'pt-tbody';
    table.appendChild(tbody);

    tableWrap.appendChild(table);
    this.container.appendChild(tableWrap);
    this.tableBody = tbody;
    this.headerRow = headerRow;

    if (this.pagination) {
      const pager = document.createElement('div');
      pager.className = 'pt-pager';
      this.container.appendChild(pager);
      this.pagerEl = pager;
    }

    this.renderBody();
    this.renderPagination();
  }

  handleSort(colIndex) {
    if (this.sortCol === colIndex) {
      this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortCol = colIndex;
      this.sortDir = 'asc';
    }
    this.applyFilters();
    this.renderBody();
    this.renderPagination();
    this.updateSortIndicators();
  }

  updateSortIndicators() {
    const ths = this.headerRow.querySelectorAll('th');
    ths.forEach((th, i) => {
      th.classList.remove('pt-sorted-asc', 'pt-sorted-desc');
      if (i === this.sortCol) {
        th.classList.add(this.sortDir === 'asc' ? 'pt-sorted-asc' : 'pt-sorted-desc');
      }
    });
  }

  renderBody() {
    const start = this.page * this.pageSize;
    const slice = this.filteredData.slice(start, start + this.pageSize);

    if (!slice.length) {
      this.tableBody.innerHTML = `<tr><td colspan="${this.columns.length}" class="pt-empty">${this.searchQuery ? 'No results match your search' : this.emptyMessage}</td></tr>`;
      return;
    }

    this.tableBody.innerHTML = slice.map((row, ri) => {
      const cells = this.columns.map((col, ci) => {
        const val = row[col.key];
        let content = val != null ? val : '';
        if (this.renderCell) {
          const rendered = this.renderCell(col.key, val, row, ri);
          if (rendered !== undefined) content = rendered;
        }
        const cls = col.className ? ' class="' + col.className + '"' : '';
        return `<td${cls}>${content}</td>`;
      }).join('');
      const clickAttr = this.onRowClick ? ` onclick="this.closest('.premium-table-wrap').__ptInstance.onRowClickHandler(${this.filteredData.indexOf(row)})"` : '';
      return `<tr${clickAttr}>${cells}</tr>`;
    }).join('');
  }

  renderPagination() {
    if (!this.pagination || !this.pagerEl) return;
    const total = Math.max(1, Math.ceil(this.filteredData.length / this.pageSize));
    if (total <= 1) {
      this.pagerEl.innerHTML = `<span class="pt-page-info">${this.filteredData.length} row${this.filteredData.length !== 1 ? 's' : ''}</span>`;
      return;
    }
    const start = this.page * this.pageSize + 1;
    const end = Math.min((this.page + 1) * this.pageSize, this.filteredData.length);
    let html = `<span class="pt-page-info">${start}\u2013${end} of ${this.filteredData.length}</span>`;
    html += `<button class="pt-page-btn" ${this.page === 0 ? 'disabled' : ''} data-action="prev">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
    </button>`;
    const maxVisible = 5;
    let pages = [];
    if (total <= maxVisible + 2) {
      for (let i = 0; i < total; i++) pages.push(i);
    } else {
      pages.push(0);
      let s = Math.max(1, this.page - 1);
      let e = Math.min(total - 2, this.page + 1);
      if (this.page <= 2) { s = 1; e = 3; }
      if (this.page >= total - 3) { s = total - 4; e = total - 2; }
      if (s > 1) pages.push('...');
      for (let i = s; i <= e; i++) pages.push(i);
      if (e < total - 2) pages.push('...');
      pages.push(total - 1);
    }
    pages.forEach(p => {
      if (p === '...') {
        html += `<span class="pt-page-ellipsis">\u2026</span>`;
      } else {
        html += `<button class="pt-page-btn ${p === this.page ? 'active' : ''}" data-page="${p}">${p + 1}</button>`;
      }
    });
    html += `<button class="pt-page-btn" ${this.page >= total - 1 ? 'disabled' : ''} data-action="next">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
    </button>`;
    this.pagerEl.innerHTML = html;

    this.pagerEl.querySelectorAll('.pt-page-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.disabled) return;
        const action = btn.dataset.action;
        if (action === 'prev') this.page = Math.max(0, this.page - 1);
        else if (action === 'next') this.page = Math.min(total - 1, this.page + 1);
        else if (btn.dataset.page !== undefined) this.page = parseInt(btn.dataset.page);
        this.renderBody();
        this.renderPagination();
      });
    });
  }

  onRowClickHandler(index) {
    if (this.onRowClick && this.filteredData[index]) {
      this.onRowClick(this.filteredData[index], index);
    }
  }

  refresh() {
    this.applyFilters();
    this.renderBody();
    this.renderPagination();
  }
}

if (typeof window !== 'undefined') {
  window.PremiumTable = PremiumTable;
}
